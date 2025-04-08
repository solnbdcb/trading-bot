import os
import ccxt
import pandas as pd
import ta
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

# تنظیمات محیطی
load_dotenv()
API_KEY = os.getenv('LBANK_API_KEY')
SECRET_KEY = os.getenv('LBANK_SECRET_KEY')

# تنظیمات صرافی
exchange = ccxt.lbank({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})

# تنظیمات استراتژی
SYMBOLS = ['KEKI/USDT', 'FART/USDT', 'BUZZ/USDT', 'FRED/USDT', 'VINE/USDT', 'SOL/USDT']
TIMEFRAME = '15m'
RISK_PERCENT = 0.01  # ۱% ریسک در هر معامله
RR_RATIO = 2  # ریسک به ریوارد ۱:۲

def fetch_ohlcv(symbol, timeframe='15m', limit=100):
    """دریافت دادههای قیمتی از LBank"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"خطا در دریافت دادههای {symbol}: {e}")
        return None

def calculate_position_size(balance, entry_price, stop_loss):
    """محاسبه حجم معامله بر اساس ریسک ۱%"""
    risk_amount = balance * RISK_PERCENT
    risk_per_unit = abs(entry_price - stop_loss)
    return risk_amount / risk_per_unit if risk_per_unit != 0 else 0

def check_breakeven(stop_loss, current_price, take_profit):
    """بررسی شرط انتقال استاپ به نقطه ورود (بیضرر)"""
    halfway = (take_profit - stop_loss) * 0.5 + stop_loss
    return current_price >= halfway

def execute_strategy(symbol):
    """اجرای استراتژی برای یک نماد"""
    try:
        # دریافت دادهها
        df_15m = fetch_ohlcv(symbol, TIMEFRAME)
        if df_15m is None or len(df_15m) < 50:
            return

        # تشخیص روند با EMA 50
        df_15m['ema50'] = ta.trend.EMAIndicator(df_15m['close'], 50).ema_indicator()
        trend = 'up' if df_15m['close'].iloc[-1] > df_15m['ema50'].iloc[-1] else 'down'

        # دریافت دادههای ۱ دقیقه برای ورود
        df_1m = fetch_ohlcv(symbol, '1m', limit=10)
        if df_1m is None:
            return

        # شناسایی سیگنال
        last_close = df_1m['close'].iloc[-1]
        swing_low = df_1m['low'].iloc[-5:].min()
        swing_high = df_1m['high'].iloc[-5:].max()

        # شرایط ورود
        if trend == 'up' and last_close > swing_high:
            entry_price = last_close
            stop_loss = swing_low * 0.995  # ۰.۵% حاشیه امن
            take_profit = entry_price + (entry_price - stop_loss) * RR_RATIO

            # محاسبه حجم
            balance = exchange.fetch_balance()['USDT']['free']
            position_size = calculate_position_size(balance, entry_price, stop_loss)

            # ارسال سفارش
            if position_size > 0:
                order = exchange.create_order(
                    symbol=symbol,
                    type='limit',
                    side='buy',
                    amount=position_size,
                    price=entry_price
                )
                print(f"سفارش خرید برای {symbol} ثبت شد: {order}")

                # تنظیم استاپ لاس و حد سود
                exchange.create_order(
                    symbol=symbol,
                    type='stop_loss',
                    side='sell',
                    amount=position_size,
                    price=stop_loss,
                    params={'stopPrice': stop_loss}
                )
                exchange.create_order(
                    symbol=symbol,
                    type='take_profit',
                    side='sell',
                    amount=position_size,
                    price=take_profit,
                    params={'stopPrice': take_profit}
                )

        # بررسی بیضرر شدن
        open_orders = exchange.fetch_open_orders(symbol)
        for order in open_orders:
            if check_breakeven(order['stopLoss'], last_close, order['takeProfit']):
                exchange.cancel_order(order['id'])
                exchange.create_order(
                    symbol=symbol,
                    type='stop_loss',
                    side='sell',
                    amount=order['amount'],
                    price=order['price'],  # نقطه ورود
                    params={'stopPrice': order['price']}
                )
                print(f"استاپ لاس برای {symbol} به بیضرر منتقل شد.")

    except Exception as e:
        print(f"خطا در اجرای استراتژی برای {symbol}: {e}")

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    scheduler.add_job(lambda: [execute_strategy(sym) for sym in SYMBOLS], 'interval', minutes=5)
    scheduler.start()
