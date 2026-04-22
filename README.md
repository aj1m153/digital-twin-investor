# 📈 Digital Twin Investor

A paper-trading platform that lets a small group of friends test real
algorithmic trading strategies on real markets — with fake money — and get a
daily email showing what their strategy did and how much "money" they have.

Built with Streamlit, SQLite, yfinance, and GitHub Actions.

## What it does

- **Invite-only signup.** Only friends with an invite code can join.
- **Pick a strategy + tickers + starting capital.** Seven built-in strategies:
  Buy & Hold, SMA Crossover, RSI Mean Reversion, MACD Momentum, Bollinger
  Mean Reversion, Dollar-Cost Averaging, and Momentum Rotation.
- **Runs itself once a day.** A GitHub Actions cron runs the daily worker,
  which pulls prices, executes each user's strategy, and emails them their
  updated portfolio — trades made today, current holdings, P&L, equity curve.
- **Streamlit dashboard.** Live portfolio values, equity curve, trade log.
  Reset and re-run a strategy at any time.
- **Works for stocks and crypto.** Any Yahoo Finance ticker: `AAPL`, `NVDA`,
  `BTC-USD`, `ETH-USD`, `SOL-USD`, etc.

## Project structure

```
digital-twin-investor/
├── app.py                      # Streamlit UI
├── daily_worker.py             # Cron-driven strategy executor
├── admin.py                    # CLI for invite codes / manual runs
├── strategies/
│   ├── __init__.py
│   └── core.py                 # All 7 strategy implementations
├── core/
│   ├── db.py                   # SQLite schema and helpers
│   ├── prices.py               # yfinance wrapper
│   ├── executor.py             # Signal → trade translation
│   └── email_sender.py         # SMTP email + HTML template
├── .github/workflows/
│   └── daily.yml               # GitHub Actions daily cron
├── data/app.db                 # SQLite DB (created on first run)
├── .env.example
├── requirements.txt
└── README.md
```

## Local setup

```bash
# 1. Clone and install
git clone <your repo url>
cd digital-twin-investor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env: add your Gmail app password and admin email

# 3. Initialise DB + create first invite code
python admin.py invite
# Copy the printed code

# 4. Run the app
streamlit run app.py
```

Sign up with the invite code, create a portfolio, and you're in.

Trigger a simulated run manually to seed the first snapshot:

```bash
python admin.py run-once
```

## Gmail SMTP setup

The email sender uses plain SMTP. Gmail needs an **app password** (not your
Google password):

1. Turn on 2FA for your Google account.
2. Go to https://myaccount.google.com/apppasswords.
3. Create an app password. Copy the 16-character code.
4. Put it in `.env` as `SMTP_PASSWORD`.

If you'd rather use Resend, SendGrid, or Mailgun, swap
`core/email_sender.py`'s `send_email` function for their SDK. The rest of the
pipeline doesn't care.

## Deploying the UI (Streamlit Cloud)

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io, connect the repo.
3. Set **Main file path** to `app.py`.
4. In **Secrets**, mirror everything from `.env`.
5. Click Deploy.

## Deploying the daily worker (GitHub Actions)

The workflow at `.github/workflows/daily.yml` runs every weekday at 14:00 UTC
(10:00 AM ET) and commits the updated SQLite file back to the repo — which
is how the Streamlit app sees the latest state.

Add these **repository secrets** in GitHub under *Settings → Secrets and
variables → Actions*:

| Name | Value |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | your Gmail |
| `SMTP_PASSWORD` | your app password |
| `SMTP_FROM` | your Gmail |

That's it. The workflow will run automatically from then on. You can also
trigger a manual run from the **Actions** tab → *Daily strategy run* → *Run
workflow*.

### Timing notes

- The cron is set to 14:00 UTC = 10:00 AM EDT / 9:00 AM EST. This is 30 min
  after US stock market open, so today's open price is already available.
- If you want the **pre-open email** your original spec described, duplicate
  the workflow at `13:00 UTC` and in that run only render+send the email
  (don't execute trades). Then run the trade execution at `14:00 UTC` as it
  does now. Easiest way: add a `--email-only` flag to `daily_worker.py`.
- Crypto is 24/7 — worker runs weekdays only by default. Add a Saturday/Sunday
  cron if you have crypto-only portfolios (there's already a commented line).

### Trade-off: SQLite-in-repo

Committing `data/app.db` back to the repo each run works but has sharp edges:

- Concurrency: don't run Streamlit writes and the worker simultaneously (the
  worker is the source of truth for position updates; the app only reads them).
- History bloat: `.db` file is binary, so git history grows. For a small
  group that's fine for years.
- Single worker: if two cron runs overlap the second will fail the push.

For something sturdier, point `DATABASE_PATH` at a hosted DB
([Turso](https://turso.tech) is a managed SQLite with a free tier;
[Supabase](https://supabase.com) is Postgres) and remove the "Persist DB"
step from the workflow.

## Adding an invite code

Once signed in as an admin user (your email must be in `ADMIN_EMAILS`), go to
*Admin → Generate new invite code* in the sidebar. Or run:

```bash
python admin.py invite
```

## Adding a new strategy

1. Write a function in `strategies/core.py` that follows the signature of the
   existing ones: `(portfolio, history, params) -> list[Signal]`.
2. Register it in `STRATEGY_REGISTRY`, `STRATEGY_DISPLAY_NAMES`, and
   `STRATEGY_DESCRIPTIONS`.
3. Optionally add a parameters block in `app.py`'s `render_create_portfolio`.

That's it — it'll show up in the dropdown and the worker will pick it up.

## What's intentionally simple

- **Execution price** = today's open (stocks) or latest available close
  (crypto). No intraday modeling.
- **Slippage + fees** = flat 10 bps per trade. Tune `DEFAULT_FEE_RATE` in
  `core/executor.py`.
- **No short selling.** Strategies can only go long or be in cash.
- **No partial fills, no market impact, no tax.** It's a strategy tester, not
  a backtesting engine — for that, check out `vectorbt`, `zipline`, or
  `backtrader`.

## Disclaimer

Paper trading. Not investment advice. Past performance does not predict
future results.
