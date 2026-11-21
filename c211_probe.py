import json, os, subprocess, sys

def run(args, timeout=70):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout or '', p.stderr or ''
    except Exception as e:
        return -1, '', repr(e)

def aws(args, timeout=70):
    return run(['aws'] + args, timeout)

res = {}

rc, out, err = aws(['sts', 'get-caller-identity', '--output', 'json'], 40)
res['identity'] = out.strip()[:1200] if rc == 0 else 'RC=%d ERR=%s' % (rc, (err or out).strip()[:800])

envd = {}
for k, v in os.environ.items():
    if k.startswith('AWS_') or k in ('ACTIONS_ID_TOKEN_REQUEST_URL', 'GITHUB_REPOSITORY', 'GITHUB_ACTOR'):
        envd[k] = len(v) if k in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN') else v[:200]
res['env'] = json.dumps(envd)

def subnets(region):
    rc, out, err = aws(['ec2', 'describe-subnets', '--region', region, '--output', 'json'])
    if rc != 0:
        return 'RC=%d %s' % (rc, (err or out).strip()[:300]), []
    try:
        d = json.loads(out)
    except Exception:
        return 'PARSE-ERR ' + out[:200], []
    items = []
    for s in d.get('Subnets', [])[:40]:
        items.append({'id': s.get('SubnetId'), 'az': s.get('AvailabilityZone'), 'cidr': s.get('CidrBlock'),
                      'pub': s.get('MapPublicIpOnLaunch'),
                      'free': s.get('AvailableIpAddressCount')})
    return json.dumps(items)[:3000], items

regions = ['ap-south-1', 'us-east-1']
subs = {}
for region in regions:
    text, items = subnets(region)
    res['subnets_' + region] = text
    subs[region] = items

for region in regions:
    rc, out, err = aws(['ec2', 'describe-vpcs', '--region', region, '--output', 'json'])
    if rc == 0:
        try:
            d = json.loads(out)
            res['vpcs_' + region] = json.dumps([{'id': v.get('VpcId'), 'cidr': v.get('CidrBlock'),
                                                 'default': v.get('IsDefault')} for v in d.get('Vpcs', [])[:10]])
        except Exception:
            res['vpcs_' + region] = 'PARSE-ERR'
    else:
        res['vpcs_' + region] = 'RC=%d %s' % (rc, (err or out).strip()[:200])

for region in regions:
    rc, out, err = aws(['ec2', 'describe-instances', '--region', region, '--output', 'json'])
    if rc == 0:
        try:
            d = json.loads(out)
            lst = []
            for r_ in d.get('Reservations', []):
                for i in r_.get('Instances', []):
                    lst.append({'id': i.get('InstanceId'), 'type': i.get('InstanceType'),
                                'state': (i.get('State') or {}).get('Name'), 'az': (i.get('Placement') or {}).get('AvailabilityZone'),
                                'ami': i.get('ImageId')})
            res['instances_' + region] = json.dumps(lst[:20])
        except Exception:
            res['instances_' + region] = 'PARSE-ERR'
    else:
        res['instances_' + region] = 'RC=%d %s' % (rc, (err or out).strip()[:200])

for region in regions:
    for code in ('L-DB2E81BA', 'L-3819A6DF'):
        rc, out, err = aws(['service-quotas', 'get-service-quota', '--service-code', 'ec2',
                            '--quota-code', code, '--region', region, '--output', 'json'])
        key = 'quota_%s_%s' % (code, region)
        if rc == 0:
            try:
                q = json.loads(out).get('Quota', {})
                res[key] = '%s=%s' % (q.get('QuotaName'), q.get('Value'))
            except Exception:
                res[key] = 'PARSE-ERR ' + out[:150]
        else:
            res[key] = 'RC=%d %s' % (rc, (err or out).strip()[:200])

for region in regions:
    for itype in ('g5.xlarge', 'p4d.24xlarge'):
        rc, out, err = aws(['ec2', 'describe-instance-type-offerings', '--region', region,
                            '--location-type', 'availability-zone',
                            '--filters', 'Name=instance-type,Values=' + itype, '--output', 'json'])
        key = 'offerings_%s_%s' % (itype, region)
        if rc == 0:
            try:
                d = json.loads(out)
                res[key] = json.dumps([o.get('Location') for o in d.get('InstanceTypeOfferings', [])][:10])
            except Exception:
                res[key] = 'PARSE-ERR'
        else:
            res[key] = 'RC=%d %s' % (rc, (err or out).strip()[:200])

for region in regions:
    rc, out, err = aws(['ssm', 'get-parameter', '--name',
                        '/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id',
                        '--region', region, '--output', 'json'])
    key = 'dlami_ssm_' + region
    if rc == 0:
        try:
            res[key] = json.loads(out)['Parameter']['Value']
        except Exception:
            res[key] = 'PARSE-ERR'
    else:
        res[key] = 'RC=%d %s' % (rc, (err or out).strip()[:150])
    rc, out, err = aws(['ec2', 'describe-images', '--owners', 'amazon', '--region', region,
                        '--filters', 'Name=name,Values=Deep Learning OSS Nvidia Driver GPU AMI (Ubuntu 22.04)*',
                        '--query', 'Images|sort_by(@,&CreationDate)[-1].[ImageId,Name,CreationDate]',
                        '--output', 'json'])
    key = 'dlami_img_' + region
    if rc == 0:
        res[key] = out.strip()[:400]
    else:
        res[key] = 'RC=%d %s' % (rc, (err or out).strip()[:200])

for region in regions:
    for itype in ('g5.xlarge', 'p4d.24xlarge'):
        sn = subs.get(region) or []
        args = ['ec2', 'run-instances', '--region', region, '--dry-run',
                '--instance-type', itype, '--image-id', 'ami-0abcdef1234567890',
                '--min-count', '1', '--max-count', '1']
        if sn:
            args += ['--subnet-id', sn[0]['id']]
        rc, out, err = aws(args, 50)
        key = 'dryrun_%s_%s' % (itype, region)
        txt = ((err or '') + (out or '')).strip()
        if 'DryRunOperation' in txt:
            res[key] = 'DRYRUN_OK ' + txt[:200]
        else:
            res[key] = 'RC=%d %s' % (rc, txt[:300])

s = json.dumps(res, indent=1)
print(s)
sys.stderr.write('C211PROBE-RESULT ' + json.dumps(res) + '\n')
sys.exit(1)
