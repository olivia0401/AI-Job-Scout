# AI Job Scout

Find current vacancies at UK Skilled Worker sponsor-licensed employers and rank them against your CV. The app runs locally; matching scores are heuristic, and a sponsor licence does not mean every role offers sponsorship.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5050`. Import the employer list, collect vacancies, then add a CV to see matches. Keep `data/` private; it is git-ignored. If you enable AI advice, CV text is sent to the provider configured by you.

## Checks

```bash
python -m pytest tests/ -q
```

See `.env.example` for optional AI settings and `docs/` for deployment details.
