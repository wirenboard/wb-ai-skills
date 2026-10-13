# Stand run — what to add to the template's checklist

The base sequence (install, import, `--version`, enabled/active after install and after reboot,
purge) is the template's "Перед контрибьютом" section:
<https://github.com/wirenboard/wb-python-service-template#перед-контрибьютом>. Below are the
review-specific steps around it. `<HOST>` is the test controller, `<PKG>` the package.

## Long operations

```bash
ssh root@<HOST> 'wb-cli --json job run <label> "<command> 2>&1"'   # → data.unit, data.log
ssh root@<HOST> 'wb-cli --json job wait --timeout 900 <data.unit>; tail -40 <data.log>'
```

Wait on `data.unit`, not on the label. Use it for apt, purge and release changes.

## Before installing

```bash
ssh root@<HOST> 'wb-cli --json info; python3 --version; df -h / | tail -1; uptime; systemctl --failed --no-legend'
ssh root@<HOST> 'apt-get install --simulate /tmp/pkg.deb | grep -E "^(Inst|E:)"'   # dependencies it pulls
```

Record load average — the comparison point for idle cost.

## Lintian (workstation, Docker)

```bash
git clone --depth 1 https://github.com/wirenboard/codestyle
docker run --rm -v "$PWD:/w" debian:trixie bash -c '
  apt-get update -qq && apt-get install -y -qq lintian >/dev/null &&
  mkdir -p ~/.lintian && cp -r /w/codestyle/lintian/profiles ~/.lintian/ &&
  lintian --include-dir=$HOME/.lintian --profile=wirenboard/trixie -I -E --pedantic /w/pkg.deb'
```

## Idle CPU

```bash
ssh root@<HOST> 'sleep 30; s() { systemctl show "$1" -p CPUUsageNSec --value; }
  a=$(s <PKG>.service); t0=$(date +%s.%N); since=$(date "+%F %T"); sleep 120
  a2=$(s <PKG>.service); t1=$(date +%s.%N)
  python3 -c "print(\"%.1f%% of one core\" % (($a2-$a)/1e9/($t1-$t0)*100))"
  journalctl -u "<PKG>-*" --since "$since" -o cat | grep Consumed; uptime'
ssh root@<HOST> 'python3 -m cProfile -s cumtime /usr/bin/<cli> <subcommand> 2>&1 | head -25'
```

Timer-fired oneshots: sum their `Consumed` seconds over the window.

## After reboot and after purge

```bash
ssh root@<HOST> 'readlink -f /etc/<PKG>.conf'          # after reboot: -> /mnt/data/etc/<PKG>.conf
ssh root@<HOST> 'systemctl list-units --all "<PKG>*" --no-legend; systemctl --failed --no-legend
  ls -d /etc/<PKG>* /mnt/data/etc/<PKG>* /var/lib/<PKG>* /var/backups/<PKG>* 2>&1; nginx -t 2>&1 | tail -1'
```

Everything still present after purge goes into the findings. Then clean the stand:
`systemctl reset-failed`, remove leftover state dirs and `/tmp/pkg.deb`, `apt autoremove`, purge
`rc` entries of packages this test installed.

## Another Debian release

Follow the target release's wiki notes. For bullseye → trixie (one-way; back up first with
`wb-controller-backup`): `apt update && apt upgrade`, then
`wb-cli --json job run debian-upgrade "wb-release --update-debian-release -y 2>&1"`, poll
`/etc/debian_version` and the job log, reboot, and repeat the run.
