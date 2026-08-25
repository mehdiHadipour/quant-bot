"""
Genuine footprint-style order-flow metrics, computed from real per-trade
data (data_engine.fetch_recent_agg_trades) rather than the candle-level
taker_buy_volume aggregate already used elsewhere in this codebase.

HONESTY NOTE (read before changing MIN_SIGNAL_PROBABILITY / wiring this
into a hard gate): this module cannot be backtested against history the
way every other filter in this project has been. Binance's aggTrades
endpoint only serves recent data (~1 hour lookback in practice), and
bulk historical tick data for a genuine 2-year backtest is many GB per
symbol — not fetchable or storable in this project's environment, and
almost certainly impractical in a free GitHub Codespace either. Every
other signal in this codebase was validated against 2 years of real
trade outcomes before being trusted (see RELEASE_NOTES — several
plausible-sounding ideas, e.g. order-flow/CVD from candle data, RSI
extremity, entry timing, were tested this way and rejected). This one
skips that validation out of necessity, not choice.

Consequently: this is wired into main.py as INFORMATIONAL ONLY, shown in
the Telegram message and logs, and does NOT block or filter any signal.
Do not promote it to a hard gate without first accumulating enough live,
forward-observed outcomes to check whether it actually correlates with
results — the same discipline used for everything else here, just
applied going forward instead of retroactively.
"""


def compute_footprint_metrics(trades_df, candle_low, candle_high, n_bins=10):
    """From raw trades (price, qty, is_buyer_maker) within a candle's
    range, compute:

    - poc_price: the price bucket with the highest total traded volume
      (point of control) — where the market spent the most volume, not
      just where it opened/closed.
    - poc_position: poc_price's position within [candle_low, candle_high]
      as a 0-1 fraction (0 = at the low, 1 = at the high). Volume
      concentrated near one extreme is a different market read than
      volume spread evenly or concentrated in the middle.
    - buy_ratio: fraction of total volume that was buyer-initiated
      (is_buyer_maker == False means the buyer crossed the spread to
      hit the ask, i.e. an aggressive buy).
    - imbalance_near_high / imbalance_near_low: buy_ratio computed
      separately for trades in the top third vs. bottom third of the
      candle's range — e.g. heavy selling concentrated specifically
      near the highs (vs. spread evenly) reads differently than the
      same overall buy_ratio would suggest alone.

    Returns None if trades_df is empty/None or the candle has no range
    (candle_high == candle_low) — callers must treat this as "no
    opinion", never as a reason to block a signal (see module docstring).
    """
    if trades_df is None or trades_df.empty or candle_high <= candle_low:
        return None

    total_qty = trades_df["qty"].sum()
    if total_qty <= 0:
        return None

    # Aggressive buy = trade where the buyer was NOT the maker (crossed
    # the spread to hit the ask).
    buy_qty = trades_df.loc[~trades_df["is_buyer_maker"], "qty"].sum()
    buy_ratio = buy_qty / total_qty

    bin_width = (candle_high - candle_low) / n_bins
    bin_idx = ((trades_df["price"] - candle_low) / bin_width).clip(0, n_bins - 1).astype(int)
    volume_by_bin = trades_df.groupby(bin_idx)["qty"].sum()
    poc_bin = volume_by_bin.idxmax()
    poc_price = candle_low + (poc_bin + 0.5) * bin_width
    poc_position = (poc_price - candle_low) / (candle_high - candle_low)

    third = (candle_high - candle_low) / 3
    near_high = trades_df[trades_df["price"] >= candle_high - third]
    near_low = trades_df[trades_df["price"] <= candle_low + third]

    def _zone_buy_ratio(zone_df):
        zone_total = zone_df["qty"].sum()
        if zone_total <= 0:
            return None
        return zone_df.loc[~zone_df["is_buyer_maker"], "qty"].sum() / zone_total

    return {
        "poc_price": poc_price,
        "poc_position": poc_position,
        "buy_ratio": buy_ratio,
        "imbalance_near_high": _zone_buy_ratio(near_high),
        "imbalance_near_low": _zone_buy_ratio(near_low),
        "trade_count": len(trades_df),
    }


def describe_footprint(metrics, direction):
    """One-line, human-readable summary of the footprint metrics for
    the Telegram message — informational only, does not judge
    agree/disagree with `direction` as a pass/fail (see module
    docstring: not validated as a filter). `direction` is used only to
    phrase the buy-pressure percentage in a way that's easy to read
    alongside the signal's own direction, not to gate anything."""
    if metrics is None:
        return "دادهٔ فوت‌پرینت در دسترس نبود (اختیاری — روی سیگنال اثر ندارد)."
    pct = metrics["buy_ratio"] * 100
    poc_pct = metrics["poc_position"] * 100
    return (
        f"فشار خرید واقعی (از {metrics['trade_count']} معاملهٔ اخیر): {pct:.0f}٪ | "
        f"نقطهٔ تمرکز حجم (POC) در {poc_pct:.0f}٪ ارتفاع کندل — صرفاً اطلاعاتی، هنوز به‌عنوان فیلتر تأیید نشده."
    )
