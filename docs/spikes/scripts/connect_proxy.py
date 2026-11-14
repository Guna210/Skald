"""Spike T03.4: a minimal logging HTTPS (CONNECT) proxy, to see which hosts uv contacts behind HTTPS_PROXY.

It tunnels bytes without touching TLS (no interception). Usage: python connect_proxy.py PORT LOGFILE
"""

import select
import socket
import socketserver
import sys


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        head = b""
        while b"\r\n\r\n" not in head:
            data = self.request.recv(65536)
            if not data:
                return
            head += data
        method, target = head.split(b"\r\n")[0].decode().split()[:2]
        with open(sys.argv[2], "a") as log:
            log.write(f"{method} {target}\n")
        if method != "CONNECT":
            self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        host, port = target.rsplit(":", 1)
        try:
            upstream = socket.create_connection((host, int(port)), timeout=30)
        except OSError:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        socks = [self.request, upstream]
        with upstream:
            while True:
                readable, _, _ = select.select(socks, [], [], 300)
                if not readable:
                    return
                for s in readable:
                    data = s.recv(1 << 18)
                    if not data:
                        return
                    (upstream if s is self.request else self.request).sendall(data)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    Server(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
