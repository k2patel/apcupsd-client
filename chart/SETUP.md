# Helm Deployment Setup

## Prerequisites

- helm v3
- sops
- age (for key generation)
- kubectl with cluster access

## 1. Install helm-secrets plugin

The plugin must register as `getter/v1` type so it works via the `secrets://` protocol handler.

```bash
# Install helm-secrets as a getter/downloader plugin
helm plugin install https://github.com/jkroepke/helm-secrets --verify=false
```

Verify it registered correctly:

```bash
helm plugin list
```

Expected output:

```
NAME       VERSION    TYPE         ...
secrets    4.x.x      getter/v1   ...
```

The `getter/v1` type means helm-secrets acts as a protocol handler.
Use `secrets://` prefix on encrypted value files instead of `helm secrets <command>`:

```bash
# Correct usage with getter/v1
helm install my-release ./chart -f values.yaml -f secrets://values-secret.yaml

# NOT: helm secrets install ... (that requires wrapper type, not getter)
```

## 2. Generate an age key

```bash
age-keygen -o ~/.config/sops/age/keys.txt
```

Note the public key from the output (starts with `age1...`).

## 3. Configure sops

Create `.sops.yaml` in the repo root:

```yaml
creation_rules:
  - path_regex: values-secret\.yaml$
    age: age1yourpublickeyhere
```

## 4. Create values files

```bash
cp chart/values.yaml.example chart/values.yaml
cp chart/values-secret.yaml.example chart/values-secret.yaml
```

Edit `chart/values.yaml` with your environment config (non-sensitive).

Edit `chart/values-secret.yaml` with sensitive values:

```bash
# Generate a session secret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate an admin password hash
python -c "from passlib.hash import argon2; print(argon2.hash('yourpassword'))"
```

## 5. Encrypt secrets

```bash
sops -e -i chart/values-secret.yaml
```

To edit later:

```bash
sops chart/values-secret.yaml    # opens in $EDITOR, re-encrypts on save
```

Or decrypt/encrypt in place:

```bash
sops -d -i chart/values-secret.yaml   # decrypt
# edit the file
sops -e -i chart/values-secret.yaml   # re-encrypt
```

## 6. Deploy

```bash
./deploy.sh install    # first time
./deploy.sh upgrade    # subsequent deploys
./deploy.sh diff       # preview changes (requires helm-diff plugin)
./deploy.sh template   # render manifests locally
./deploy.sh status     # show running pods/services
./deploy.sh logs       # tail app logs
./deploy.sh restart    # rolling restart
./deploy.sh destroy    # uninstall
```
