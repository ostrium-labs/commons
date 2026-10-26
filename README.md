# Ostrium commons

This repository is the public registry behind the [Ostrium hub](https://hub.ostriumlabs.org)'s community papers. It holds two things:

- **`tracks/`**: research tracks. Anyone with a registered key can submit papers to a track, and the track's maintainers approve them.
- **`keys/`**: the OpenPGP public keys that may sign changes here.

Community papers are **not Ostrium research, not evidence, and not peer-reviewed**. A maintainer's approval checks that a paper fits the track's scope and is safe to publish. It does not certify that the paper is correct.

## Register a track

1. Add your public key, if it isn't here yet. Export it with `gpg --armor --export <FINGERPRINT> > keys/<FINGERPRINT>.asc`. The file name is the full fingerprint, in upper-case hex.
2. Add `tracks/<slug>.toml`:

   ```toml
   slug = "temporal-compute"        # must equal the file name; a-z, 0-9 and "-", 3–48 characters
   name = "Temporal compute"        # 3–80 characters
   scope = """
   What belongs in this track, in one or two paragraphs (at most 1000 characters).
   """
   maintainers = ["0123…ABCD"]     # 1–10 full fingerprints, each present in keys/
   ```

3. **Sign every commit** with a key in `keys/` (`git commit -S`). A PR can add its own signer's key file.
4. Open a pull request. CI checks the schema and every commit signature, and a member of `@ostrium-labs/maintainers` must approve.

After a merge, the hub imports the change with `ostrium-hub tracks sync`.

To change an existing track, sign your commits with the key of one of that track's current maintainers.

## Rules the CI enforces

`scripts/check.py` checks the following, and fails the PR if any rule breaks:

- Every track file parses, its fields are valid, and its slug matches its file name.
- Every maintainer fingerprint has a file in `keys/`.
- Every key file holds exactly one primary key, and its file name matches that key's fingerprint.
- Every commit in the PR has a valid signature from a key in `keys/`, as of the PR's head commit.
- A commit that changes an existing track is signed by one of that track's maintainers at the PR's base.

## Licence

Everything here is published under [CC0 1.0](LICENSE): track descriptions and public keys are facts meant to be copied.
