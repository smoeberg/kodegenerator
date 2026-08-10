P6-03 concrete backend: `BubblewrapProcessAdapter` in `phase6/execution/process.py`.

The backend fails closed without Linux bubblewrap, denies network by namespace isolation, and requires an explicit executable allowlist.