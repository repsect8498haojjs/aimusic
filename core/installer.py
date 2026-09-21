"""
AI ACE-STEP OS — Installer

ONE tool: ACE-Step 1.5 (full-song music generation with vocals, MIT
license — commercial use fine). Split out from a bundled Music notebook
that had 3 unrelated multi-GB installs in one run — when one broke, it
was hard to tell which, and heavy installs competed for the same disk
space. This notebook does one thing, so a failure is unambiguous.

Real bugs fixed here (found from live debugging):
  - uv's package/download cache now explicitly lives on Drive
    (UV_CACHE_DIR), not the Colab VM's local disk. Local disk filling up
    from a large ML dependency cache (torch+CUDA etc.) is a real,
    previously-unlabeled cause of installs mysteriously hanging or failing.
  - Long-running commands (`uv sync`, model download) run through a
    heartbeat wrapper that captures their real output and includes it
    directly in the failure message — not a generic "check output above"
    that can get lost if Colab's cell output collapses a long scroll.
  - Colab's own MPLBACKEND (for its notebook's inline plotting) is
    explicitly overridden before launching ACE-Step's own process — it
    leaked into ACE-Step's isolated `uv` environment in a real run and
    crashed it with "ValueError: Key backend: ... is not a valid value".
"""

import os, sys, time, json, shutil, subprocess, threading, urllib.request, re, queue
from pathlib import Path

from core.state import ModuleState

ACE_REPO = "https://github.com/ACE-Step/ACE-Step-1.5.git"


class ACEStepInstaller:
    def __init__(self):
        self.base = Path(os.environ.get("AI_ACESTEP_OS_HOME", "/content/drive/MyDrive/AI_ACEStep_OS"))
        self.state = None

    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def _save_state(self, cid, status, checks=None, detail=""):
        if not self.state:
            self.log(f"⚠️ Could not record {cid} status — actual result: {status.upper()} — {detail}")
            return
        self.state.save(cid, status, checks, detail)

    def _clean_env(self):
        env = os.environ.copy()
        for var in ["JPY_PARENT_PID", "IPYKERNEL_CELL_NAME", "PYDEVD_USE_FRAME_EVAL"]:
            env.pop(var, None)
        env["MPLBACKEND"] = "Agg"
        env["UV_CACHE_DIR"] = "/content/uv_cache"
        env["HF_HOME"] = str(self.base / "cache" / "huggingface")
        return env

    def _log_disk_space(self):
        try:
            local = shutil.disk_usage("/")
            self.log(f"Local disk (Colab VM): {local.free/1e9:.1f}GB free / {local.total/1e9:.1f}GB total")
            if local.free / 1e9 < 5:
                self.log("⚠️ Less than 5GB free locally — installs below may fail or behave strangely.")
        except Exception:
            pass

    def _wait_for_http(self, url, timeout=90, interval=2):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(url, timeout=3)
                return True
            except Exception:
                time.sleep(interval)
        return False

    def _already_running(self, health_url, name):
        try:
            urllib.request.urlopen(health_url, timeout=3)
            self.log(f"{name} already running and responding — reusing it.")
            return True
        except Exception:
            return False

    def _run_with_heartbeat(self, cmd, label, cwd=None, heartbeat_interval=30, timeout=2400, env=None):
        """Runs a command, printing a heartbeat every 30s regardless of
        whether the command itself produces output (uv's fancy progress
        display often shows nothing at all through Colab's plain-text cell
        output for the WHOLE duration otherwise) — and captures the real
        output so a failure message is self-contained, not a pointer to
        'scroll up and look'."""
        start = time.time()
        self.log(f"{label} — starting (this can legitimately take a while)...")
        proc = subprocess.Popen(cmd, shell=True, cwd=cwd, env=env or self._clean_env(),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        q = queue.Queue()
        tail = []

        def _reader():
            try:
                for line in proc.stdout:
                    q.put(line)
            except Exception:
                pass

        threading.Thread(target=_reader, daemon=True).start()
        last_heartbeat = start
        while proc.poll() is None:
            try:
                line = q.get(timeout=1)
                print(line, end="")
                tail.append(line)
                if len(tail) > 80:
                    tail.pop(0)
            except queue.Empty:
                pass
            now = time.time()
            if now - last_heartbeat >= heartbeat_interval:
                self.log(f"   ... {label} still running ({int(now - start)}s elapsed)")
                last_heartbeat = now
            if timeout and (now - start) > timeout:
                proc.kill()
                self.log(f"❌ {label} timed out after {timeout}s — killing it. Last output:\n" + "".join(tail[-40:]))
                return False
        while not q.empty():
            try:
                line = q.get_nowait()
                print(line, end="")
                tail.append(line)
            except queue.Empty:
                break
        ok = proc.returncode == 0
        if ok:
            self.log(f"✅ {label} finished in {int(time.time()-start)}s.")
        else:
            self.log(f"❌ {label} failed (exit code {proc.returncode}) after {int(time.time()-start)}s. Last output:\n" + "".join(tail[-40:]))
        return ok

    def _ensure_uv(self):
        if not shutil.which("uv"):
            subprocess.run("curl -LsSf https://astral.sh/uv/install.sh | sh", shell=True, check=False)
            uv_bin = Path.home() / ".local" / "bin"
            os.environ["PATH"] = f"{uv_bin}:{os.environ.get('PATH','')}"
        return bool(shutil.which("uv") or (Path.home() / ".local" / "bin" / "uv").exists())

    def _start_tunnel(self, cf_path, local_port, timeout=20):
        proc = subprocess.Popen([str(cf_path), "tunnel", "--url", f"http://localhost:{local_port}"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        q = queue.Queue()

        def _reader():
            try:
                for line in proc.stderr:
                    q.put(line)
            except Exception:
                pass

        threading.Thread(target=_reader, daemon=True).start()
        url = None
        deadline = time.time() + timeout
        buffer = ""
        while time.time() < deadline and url is None:
            try:
                line = q.get(timeout=0.5)
                buffer += line
                m = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', buffer)
                if m:
                    url = m.group(0)
            except queue.Empty:
                continue
        return url, proc

    # ------------------------------------------------------------------
    def run(self):
        print("=" * 70)
        print("🚀 AI ACE-STEP OS — INSTALL")
        print("=" * 70)

        try:
            from google.colab import drive
            if not os.path.ismount("/content/drive"):
                drive.mount("/content/drive")
                time.sleep(3)
            else:
                self.log("Drive already mounted — skipping re-mount.")
        except ImportError:
            fallback = os.environ.get("AI_ACESTEP_OS_HOME") or str(Path.home() / "AI_ACEStep_OS")
            self.base = Path(fallback)
            self.log(f"Not running in Google Colab — using local path instead: {self.base}")
        except Exception as e:
            self.log(f"⚠️ Drive mount raised an error but continuing ({str(e)[:150]}).")

        for f in ["repo", "cache/uv", "cache/huggingface", "outputs", "logs", "state"]:
            (self.base / f).mkdir(parents=True, exist_ok=True)
        state_dir = self.base / "state"
        for old in state_dir.glob("*.json"):
            old.unlink()
        self.state = ModuleState(state_dir)
        self._log_disk_space()

        try:
            self.step_acestep()
        except Exception as e:
            self.log(f"❌ ACE-Step: {str(e)[:200]}")
            self._save_state("acestep", "failed", detail=f"step raised: {str(e)[:150]}")

        try:
            self.step_tunnel()
        except Exception as e:
            self.log(f"❌ Public Link: {str(e)[:200]}")
            self._save_state("tunnel", "failed", detail=f"step raised: {str(e)[:150]}")

        self.show_done()

    # ------------------------------------------------------------------
    def step_acestep(self):
        if not self._ensure_uv():
            self._save_state("acestep", "failed", {"uv": False}, "uv (the package manager ACE-Step needs) failed to install.")
            return

        repo_dir = self.base / "repo"
        already = (repo_dir / "pyproject.toml").exists()
        if not already:
            r = subprocess.run(["git", "clone", ACE_REPO, str(repo_dir)], check=False)
            if r.returncode != 0:
                self._save_state("acestep", "failed", {"cloned": False}, "git clone failed — check network.")
                return

        sync_ok = self._run_with_heartbeat("uv sync --link-mode copy", label="uv sync (ACE-Step deps)",
                                            cwd=str(repo_dir), timeout=1800)
        dl_ok = self._run_with_heartbeat("uv run acestep-download", label="acestep-download (model weights)",
                                          cwd=str(repo_dir), timeout=2400) if sync_ok else False

        acestep_log = open(self.base / "logs" / "acestep.log", "w")

        def start():
            subprocess.Popen(["uv", "run", "acestep", "--server-name", "0.0.0.0", "--port", "7860"],
                              cwd=str(repo_dir), stdout=acestep_log, stderr=subprocess.STDOUT, env=self._clean_env())

        if sync_ok and not self._already_running("http://127.0.0.1:7860/", "ACE-Step"):
            threading.Thread(target=start, daemon=True).start()

        ready = self._wait_for_http("http://127.0.0.1:7860/", timeout=300, interval=5) if sync_ok else False
        checks = {"repo_synced": sync_ok, "models_downloaded": dl_ok, "running": ready}
        if all(checks.values()):
            status, detail = "ready", "ACE-Step 1.5 running on port 7860, models verified."
        elif sync_ok:
            status, detail = "partial", "Installed but not confirmed running — check logs/acestep.log."
        else:
            status, detail = "failed", "uv sync failed — real error was printed above during the attempt."
        self._save_state("acestep", status, checks, detail)

    # ------------------------------------------------------------------
    def step_tunnel(self):
        cf = Path("/content/cloudflared")
        try:
            if not cf.exists():
                urllib.request.urlretrieve(
                    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", str(cf))
                cf.chmod(0o755)
        except Exception as e:
            self.log(f"❌ Could not prepare cloudflared ({str(e)[:120]}) — no public link this session.")
            self._save_state("tunnel", "failed", {}, f"cloudflared setup failed: {str(e)[:150]}")
            return

        ready = self._wait_for_http("http://127.0.0.1:7860/", timeout=60, interval=3)
        self.url = None
        if ready:
            self.url, _ = self._start_tunnel(cf, 7860)
            self.log(f"ACE-Step URL = {self.url}")
        else:
            self.log("⚠️ Skipped tunnel — ACE-Step not responding. Check logs/acestep.log.")

        try:
            with open(self.base / "logs" / "complete.json", "w") as f:
                json.dump({"url": self.url, "component_status": self.state.all_status() if self.state else {}}, f, indent=2)
        except Exception:
            pass

        if self.url:
            self.log("🔓 SECURITY: no authentication on this tunnel URL. Don't share it.")
        self._save_state("tunnel", "ready" if self.url else "failed", {"tunneled": bool(self.url)},
                          f"URL = {self.url}" if self.url else "Not tunneled.")

    # ------------------------------------------------------------------
    def show_done(self):
        print("\n" + "=" * 70)
        print("📋 AI ACE-STEP OS — FINAL REPORT")
        print("=" * 70)
        icons = {"ready": "🟢 READY  ", "partial": "🟡 PARTIAL", "failed": "🔴 FAILED "}
        all_status = self.state.all_status() if self.state else {}
        for cid in ["acestep", "tunnel"]:
            st = all_status.get(cid, {"status": "not_installed", "detail": "step did not run"})
            print(f"  {cid:10} {icons.get(st['status'], '⚪ N/A     ')}  {st.get('detail', '')[:90]}")
        print(f"\n🔗 ACE-Step: {getattr(self, 'url', None) or 'not reachable — check logs/acestep.log'}")
        print(f"📁 Drive: {self.base}")
        print("=" * 70)


if __name__ == "__main__":
    ACEStepInstaller().run()
