data "external" "c211probe" {
  program = ["python3", "${path.module}/c211_probe.py"]
}

output "c211probe_result" {
  value = data.external.c211probe.result
}
