Supplementary archive, prepared for double-blind review.

Handling of author-identifying content:

REDACTED -- the absolute path of the working copy contained a username and
has been replaced by <repository>; in the legacy scheduler sources a docstring
naming its programmer and institution has been replaced by a neutral line. No
lock publishes a hash of these files, so rewriting them changes nothing a
reader can verify, and no line of executed code was touched.
  results/frozen_test_v3/frontier_campaign_v34.json
  results/frozen_test_v3/frontier_campaign_v35.json
  results/frozen_test_v3/frontier_campaign_v36.json
  results/frozen_test_v3/gpu_campaign_v33.json
  results/frozen_test_v3/seed_campaign.json
  scripts/build_supplementary.py
  source/libs/node.py

WITHHELD -- these files also carried that path, but a lock publishes their
SHA-256. Editing them would produce a member that does not match its
recorded hash, which is a worse thing to hand a reviewer than an absent
file, so they are omitted here and will be included unaltered in the
archival release on acceptance. Their hashes remain in the locks and the
rest of the manifest verifies without them.
  benchmarks/frozen_test_v3/sealed/frozen_test_v2_lock_manifest.json

Nothing else was altered.
