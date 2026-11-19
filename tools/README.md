# Tools

Tools used for development and iteration of the software and applications.

## Pushing files to device

The device doesn't have any SSH or FTP server, however the HTTP server that
serves the file manager supports uploading files. This can be used to quickly
push code to the device remotely without having to plug it into the computer.

Since the server treats binary files differently from text, you can either rely
on auto-discovery or force binary mode, which uses the REPL to encode and decode
the binary bytes. This is used for `.mpy` files.

```sh
# Usage: python3 tools/push.py <local> <device_path> [--host IP]
#
# Example:
MATRIXBOX_HOST=192.168.1.10 python3 tools/push.py apps/my_app/code.mpy /my_app/code.mpy
```

### Full deploy loop

`/fm/write` and `/repl` are only registered on the selector screen; a running app
calls `ampule.routes.clear()` and installs its own, so pushing while an app runs
returns `404`. Exit first, push, then hard reset. The app only notices `/exit` at the
end of its current main-loop pass, so wait until `/repl` answers before pushing.

```sh
IP=192.168.1.113
R=~/Documents/Arduino/matrixbox
curl -s -m 5 "http://$IP/exit" >/dev/null
for i in $(seq 1 40); do
  printf 'print(1)' | base64 | curl -s -m 3 "http://$IP/repl" --data-binary @- | grep -q '"ok"' && break
  sleep 1
done
for f in functions varinit web createhtml; do
  python3 $R/tools/push.py $R/apps/departures/$f.py /departures/$f.py --host $IP
done
printf 'import microcontroller;microcontroller.reset()' | base64 | curl -s "http://$IP/repl" --data-binary @-
sleep 25
echo done
```

Apps live at the device root as `/appname`, so `apps/departures/x.py` pushes to
`/departures/x.py`. Relaunch without a reset via `curl "http://$IP/?run=departures"`.
