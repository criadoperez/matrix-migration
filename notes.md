# Install Synapse (Matrix Server) on Debian 13 for a test migration

```bash
apt install -y python3 python3-venv python3-pip build-essential libpq5 libssl-dev libffi-dev libjpeg-dev libxslt1-dev libpq-dev

python3 -m venv synapse-env
source synapse-env/bin/activate

pip install --upgrade pip
pip install matrix-synapse

```

Generate initial configuration

```bash
cd ~/synapse-env
python3 -m synapse.app.homeserver \
  --server-name your.domain.tld \
  --config-path homeserver.yaml \
  --generate-config \
  --report-stats=no

```

That will output `homeserver.yaml` and `signing.key`

Start with:

```bash
synctl start 
```
