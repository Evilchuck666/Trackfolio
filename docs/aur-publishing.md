# Publishing trackfolio-bin to AUR

The optional AUR job in `release.yml` publishes the **recipe**, not the binary.
Users download the Linux x64 onefile archive from the corresponding GitHub
release. Python is not a runtime dependency. The package installs `trackfolio`,
a desktop entry and its icon. Both X11 and Wayland dependencies are declared.

## One-time manual authentication setup

Complete these steps **before running the release workflow**:

1. Create and verify your account at <https://aur.archlinux.org/>. Check that
   `trackfolio-bin` is available, or that your account is its maintainer or
   co-maintainer. Authentication alone does not grant access to somebody else's
   package. This setup has not reserved the name.
2. Generate a dedicated automation key on your computer, using a new filename
   so that you do not overwrite another key:

   ```sh
   ssh-keygen -t ed25519 -C "Trackfolio AUR GitHub Actions" -f ~/.ssh/trackfolio-aur-actions -N ''
   ```

   This dedicated key must have **no passphrase** for unattended use. Add the
   entire contents of `~/.ssh/trackfolio-aur-actions.pub` to the **SSH Public Key**
   field of your AUR account. Keep any existing public keys you still use.
   Never commit the private key or paste it into an issue, log or chat.
3. Obtain the AUR server host key and verify it independently:

   ```sh
   ssh-keyscan -t ed25519 aur.archlinux.org > /tmp/trackfolio-aur-known-hosts
   ssh-keygen -lf /tmp/trackfolio-aur-known-hosts
   ```

   Compare the fingerprint with the one published by Arch on the AUR website
   or its [authentication documentation](https://wiki.archlinux.org/title/AUR_submission_guidelines#Authentication).
   `ssh-keyscan` by itself does **not** authenticate the server. Do not proceed
   if the fingerprints differ. The workflow requires a verified host key and
   does not disable host-key checking or blindly trust a scan.
4. Test the dedicated key and verified host entry locally:

   ```sh
   ssh -i ~/.ssh/trackfolio-aur-actions -o IdentitiesOnly=yes -o BatchMode=yes \
     -o StrictHostKeyChecking=yes \
     -o UserKnownHostsFile=/tmp/trackfolio-aur-known-hosts \
     aur@aur.archlinux.org list-repos
   ```

   This should complete without a password prompt; an account with no packages
   can return an empty list. The SSH user is always **aur**, not your account
   name. `Permission denied (publickey)` means the uploaded public key does not
   match, the account setup is incomplete, or the wrong identity was used.
5. In the Trackfolio GitHub repository, open **Settings → Secrets and variables
   → Actions** and create these **repository secrets**:

   | Secret | Value |
   | --- | --- |
   | `AUR_SSH_PRIVATE_KEY` | The complete private file `~/.ssh/trackfolio-aur-actions`, including BEGIN/END lines and newlines |
   | `AUR_KNOWN_HOSTS` | The complete verified `/tmp/trackfolio-aur-known-hosts` contents, not just the fingerprint |

   In the **Variables** tab, create `AUR_GIT_NAME` and `AUR_GIT_EMAIL` for the
   public AUR commit author identity. A GitHub PAT is not required: GitHub
   releases use the workflow token; AUR uses the dedicated SSH key.

## Publish

Commit and push the workflow and packaging changes to `main` yourself. Follow
the [release instructions](standalone-build.md#publish-a-release): enter the
version matching `pyproject.toml` and enable **publish_aur** in **Run workflow**.
Leaving the option disabled keeps the existing GitHub-only release behavior.

After the GitHub release succeeds, the AUR job downloads its Linux archive and
verifies the published checksum. `scripts/prepare_aur.py` renders
`packaging/aur/PKGBUILD` with the exact version and SHA256 values for every
source. The committed recipe is a template: its placeholder checksum deliberately
prevents using an unverified or unpublished release. No `SKIP` checksum is used.

An Arch Linux container runs `makepkg --syncdeps` as an unprivileged user and
generates `.SRCINFO` with `makepkg --printsrcinfo`. Only after that succeeds does
the runner load the SSH key and push `PKGBUILD`, `.SRCINFO`, the desktop entry and
the icon to `ssh://aur@aur.archlinux.org/trackfolio-bin.git` on `master`. It never
force-pushes. The initial push creates an unclaimed package repository.

If AUR publication fails after the release was created, fix the credentials or
permissions and use **Re-run failed jobs** on that same run. Do not start a new
release with the same version: the release job rejects existing tags. Identical
recipes produce no new AUR commit. Packaging-only revisions should increment
`pkgrel`; the release workflow is intended for new upstream versions.

The workflow and authentication have not been executed against your AUR account.
The server may still reject a push for package ownership or policy reasons even
after SSH authentication succeeds.

References: [PKGBUILD](https://man.archlinux.org/man/PKGBUILD.5.en),
[SRCINFO](https://man.archlinux.org/man/SRCINFO.5.en).
