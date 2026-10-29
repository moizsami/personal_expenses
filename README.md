## Personal Expenses

Builded frontend app for frontend builder

#### License

mit

## SMS Expense Parser

Paste bank SMS messages (HSBC, CIB) into an **SMS Import**, click **Parse**, and each message becomes an
**SMS Transaction**. Transactions that match an **SMS Match Rule** create a Personal Expense, a Journal Entry
or a Purchase Invoice automatically; the rest wait in *SMS Transactions (Needs Review)*. Everything is on the
**SMS Parser** workspace.

Setup (**SMS Parser Settings**):

- **SMS Senders**: the SMS thread name on your phone (e.g. `HSBC`, `CIB Egypt`) and the bank it belongs to.
  An import only tries the patterns of its sender's bank.
- **Bank Accounts**: the account / card digits as they appear in the SMS (`8013`, `111`, `9014`), the Personal
  Expense payment source, and the ERP account and Mode of Payment for company entries. For a credit card,
  use a liability account whose Account Type is *not* Payable (a Payable account needs a party on every entry).

### Adding a new bank SMS format

1. Copy one real SMS of the new format.
2. Create an **SMS Pattern**:
   - **Bank**, and a **Priority** (lower runs first).
   - **Message Start Marker**: the literal text every message of this format starts with, e.g.
     `Your credit card ending with#`. The pasted text is split into messages at these markers, so a message
     that wraps over several lines still parses as one.
   - **Regex** with named groups. `amount` and `date` are required, and `sign` too when Direction Rule is
     *From sign*. The others are optional: `merchant`, `counterparty`, `account`, `currency`, `balance_currency`,
     `balance`, `reference`, `time`. Use `\s+` between words; spacing in bank SMS varies.
   - **Date Format** in Python `strptime` syntax, e.g. `%d%b%y` (15OCT26), `%d-%m-%Y`, `%d/%m/%y`.
   - **Direction Rule**: *Debit*, *Credit*, or *From sign* (`-` debit, `+` credit).
   - **Sample Message**: paste the SMS; saving fails if the regex doesn't parse it.
3. For messages to ignore (adverts, PIN warnings, link lines) tick **Is Noise**. Leave the start marker empty
   to drop single lines (e.g. `^\[.*\]\(https?://.*\)$`), or set one (e.g. `Dear Customer,`) so a multi-line
   announcement is cut off as one block.

A message no pattern recognises becomes an SMS Transaction with status **Error** that shows the raw text, so
new formats are easy to spot. No code change or migrate is needed.

### Adding a keyword rule

Create an **SMS Match Rule** (or, while reviewing a transaction, tick **Save as New Rule** before submitting):

- **Keywords**: any keyword matching makes the rule match. Match on Merchant, Counterparty or the full SMS
  text, using Contains / Exact / Regex (all case-insensitive).
- Optional filters: Bank, Currency, Direction (credits are only matched by *Credit* rules).
- **Is Company Expense** off: pick the Personal Expense Category. On: pick Journal Entry (expense account) or
  Purchase Invoice (supplier and item), plus a cost center.
- **Description Template**, e.g. `{merchant} {date}`.

Rules are tried by Priority. USD transactions use the last USD→EGP rate you submitted (shown in the settings);
change it on the transaction before submitting.

Run the tests with:

```
CI=1 bench --site <site> run-tests --module personal_expenses.personal_expenses.doctype.sms_import.test_sms_import --skip-test-records --skip-before-tests
```
