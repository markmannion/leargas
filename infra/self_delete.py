"""Delete THIS Verda instance (M9 overnight auto-stop).

!! On Verda a *shut down* instance keeps billing. Only DELETE stops compute charges
   (docs.verda.com: "Shutdown, hibernate and delete"). So `sudo shutdown -h now` at the end of
   run 2 would still burn ~$3/h until morning. Use this instead:

   python model/train_lora.py ... ; python infra/self_delete.py --hostname "$(hostname)" --yes

Checkpoints must already be on HF (train_lora.py pushes every save). Attached block volumes
are kept and billed per GB: delete them in the dashboard on Sunday (dataset licence: Junction use only).

Needs: pip install verda ; env VERDA_CLIENT_ID / VERDA_CLIENT_SECRET (Verda dashboard -> Keys).
Test it at setup time with --dry-run so the morning isn't a surprise.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hostname", default=socket.gethostname())
    ap.add_argument("--yes", action="store_true", help="actually delete (otherwise prints what it would do)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from verda import VerdaClient
    from verda.constants import Actions

    client = VerdaClient(os.environ["VERDA_CLIENT_ID"], os.environ["VERDA_CLIENT_SECRET"])
    instances = client.instances.get()
    mine = [i for i in instances if getattr(i, "hostname", None) == a.hostname]
    print(f"instances on account: {[(i.hostname, i.instance_type, i.status) for i in instances]}")
    if len(mine) != 1:
        sys.exit(f"!! expected exactly one instance with hostname {a.hostname!r}, found {len(mine)}; not deleting")
    inst = mine[0]
    print(f"target: {inst.id} {inst.hostname} {inst.instance_type} {inst.status}")
    if a.dry_run or not a.yes:
        print("dry run: pass --yes to delete")
        return
    client.instances.action(inst.id, Actions.DELETE)
    print("delete requested")


if __name__ == "__main__":
    main()
