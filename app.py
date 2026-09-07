import os
import sqlite3
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# LECTURA OBLIGATORIA DESDE EL PANEL DE RENDER
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
DB_NAME = "wta_bot.db"

PREMATCH_CACHE = {}
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot WTA Activo y Escaneando el Circuito en Vivo", 200

def send_telegram_alert(tournament, p1, p2, fav_name, pre_odds, live_odds, prob):
    """Envía la alerta estructurada a Telegram usando variables de entorno."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Faltan credenciales de Telegram.")
        return
    url = f"https://telegram.org{TELEGRAM_BOT_TOKEN}/sendMessage"
    html_content = (
        f"<b>🚨 ALERTA DE VALOR WTA 🚨</b>\n\n"
        f"🏆 <b>Torneo:</b> {tournament.replace('_', ' ').upper()}\n"
        f"🎾 <b>Partido:</b> {p1} vs {p2}\n"
        f"⭐ <b>Favorita en Apuros:</b> {fav_name}\n\n"
        f"📊 <b>Comparativa de Cuotas:</b>\n"
        f"• Cuota Pre-Partido: {pre_odds}\n"
        f"• Cuota en Vivo Actual: {live_odds}\n\n"
        f"🎯 <b>Probabilidad de Remontada:</b> {prob}%"
    )
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": html_content, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        logging.info(f"Envío de alerta. Estado Telegram: {r.status_code}")
    except Exception as e:
        logging.error(f"Error conectando con Telegram: {e}")

def send_startup_test_message():
    """Envía un mensaje de prueba estándar al iniciar para validar tokens."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Faltan credenciales de Telegram.")
        return
    url = f"https://telegram.org{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "<b>✅ Bot WTA Iniciado Correctamente</b>\nEl sistema unificado ya está activo y leyendo las variables del panel de Render de forma limpia.",
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            logging.info("🚀 ¡Mensaje de prueba enviado con éxito a Telegram!")
        else:
            logging.error(f"❌ Falló mensaje de prueba. Código: {r.status_code}.")
    except Exception as e:
        logging.error(f"❌ Error de conexión con Telegram: {e}")

def calculate_comeback_probability(pre_odds_fav, live_odds_fav):
    if not pre_odds_fav or pre_odds_fav <= 1.0: return 50.0
    base_prob = (1.0 / pre_odds_fav) * 100
    strength_bonus = 10.0 if pre_odds_fav <= 1.30 else (5.0 if pre_odds_fav <= 1.60 else 0.0)
    live_drop_factor = (pre_odds_fav / live_odds_fav) * 10
    estimated_prob = base_prob + strength_bonus - (10 - live_drop_factor)
    return round(max(10.0, min(90.0, estimated_prob)), 1)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wta_matches (
            match_id TEXT PRIMARY KEY, tournament TEXT, player_1 TEXT, player_2 TEXT,
            p1_pre_odds REAL, p2_pre_odds REAL, fav_name TEXT, fav_pre_odds REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_active_wta_tournaments():
    if not ODDS_API_KEY: return []
    url = f"https://the-odds-api.com{ODDS_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return [s['key'] for s in r.json() if 'tennis_wta' in s['key']]
        return []
    except Exception as e:
        logging.error(f"Error obteniendo torneos: {e}")
        return []

def fetch_single_match_odds(sport_key, match_id, p1, p2):
    url = f"https://the-odds-api.com{sport_key}/odds/"
    params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            for m in r.json():
                if m.get('id') == match_id:
                    bookmakers = m.get('bookmakers', [])
                    p1_odds, p2_odds = None, None
                    if bookmakers and len(bookmakers) > 0:
                        for bookmaker in bookmakers:
                            markets = bookmaker.get('markets', [])
                            if markets and len(markets) > 0:
                                for o in markets.get('outcomes', []):
                                    if o.get('name') == p1: p1_odds = o.get('price')
                                    elif o.get('name') == p2: p2_odds = o.get('price')
                                break
                    
                    if p1_odds and p2_odds:
                        fav_name = p1 if p1_odds < p2_odds else p2
                        fav_pre_odds = p1_odds if p1_odds < p2_odds else p2_odds
                        conn = sqlite3.connect(DB_NAME)
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT OR REPLACE INTO wta_matches (match_id, tournament, player_1, player_2, p1_pre_odds, p2_pre_odds, fav_name, fav_pre_odds)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (match_id, sport_key, p1, p2, p1_odds, p2_odds, fav_name, fav_pre_odds))
                        conn.commit()
                        conn.close()
                        logging.info(f"💾 PRE-PARTIDO REGISTRADO: {p1} vs {p2}")
    except Exception as e:
        logging.error(f"Error en snapshot pre-partido: {e}")

def schedule_wta_matches(scheduler):
    wta_tournaments = get_active_wta_tournaments()
    for sport_key in wta_tournaments:
        url = f"https://the-odds-api.com{sport_key}/odds/"
        params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                now = datetime.utcnow()
                for match in r.json():
                    match_id = match.get('id')
                    p1 = match.get('home_team')
                    p2 = match.get('away_team')
                    commence_str = match.get('commence_time')
                    if commence_str and match_id not in PREMATCH_CACHE:
                        commence_dt = datetime.strptime(commence_str, "%Y-%m-%dT%H:%M:%SZ")
                        t5_dt = commence_dt - timedelta(minutes=5)
                        if t5_dt > now:
                            scheduler.add_job(fetch_single_match_odds, 'date', run_date=t5_dt, args=[sport_key, match_id, p1, p2], id=f"t5_{match_id}", replace_existing=True)
                            PREMATCH_CACHE[match_id] = True
                        elif now <= commence_dt:
                            fetch_single_match_odds(sport_key, match_id, p1, p2)
                            PREMATCH_CACHE[match_id] = True
        except Exception as e:
            logging.error(f"Error al programar cartelera: {e}")

def monitor_live_matches():
    """Escáner real del circuito WTA en directo."""
    logging.info("🔄 Verificando partidos EN VIVO circuito WTA...")
    wta_tournaments = get_active_wta_tournaments()
    for sport_key in wta_tournaments:
        url = f"https://the-odds-api.com{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                for match in r.json():
                    match_id = match.get('id')
                    conn = sqlite3.connect(DB_NAME)
                    cursor = conn.cursor()
                    cursor.execute("SELECT tournament, player_1, player_2, fav_name, fav_pre_odds FROM wta_matches WHERE match_id=?", (match_id,))
                    db_data = cursor.fetchone()
                    conn.close()
                    
                    if db_data:
                        tournament, p1, p2, fav_name, fav_pre_odds = db_data
                        bookmakers = match.get('bookmakers', [])
                        if bookmakers and len(bookmakers) > 0:
                            live_odds_fav = None
                            for bookmaker in bookmakers:
                                markets = bookmaker.get('markets', [])
                                if markets and len(markets) > 0:
                                    for o in markets.get('outcomes', []):
                                        if o.get('name') == fav_name: 
                                            live_odds_fav = o.get('price')
                                    break
                                
                            if live_odds_fav and fav_pre_odds:
                                if live_odds_fav >= (fav_pre_odds * 1.4):
                                    prob = calculate_comeback_probability(fav_pre_odds, live_odds_fav)
                                    send_telegram_alert(tournament, p1, p2, fav_name, fav_pre_odds, live_odds_fav, prob)
        except Exception as e:
            logging.error(f"Error en monitoreo en vivo: {e}")

# --- INICIALIZADOR ---
send_telegram_alert("PRUEBA_FINAL_EXITOSA", "Marta Kostyuk", "Linda Noskova", "Marta Kostyuk", 1.40, 2.20, 72.5)
init_db()
send_startup_test_message()

scheduler = BackgroundScheduler()
scheduler.add_job(func=lambda: schedule_wta_matches(scheduler), trigger="interval", minutes=60, id="cartelera")
scheduler.add_job(func=monitor_live_matches, trigger="interval", minutes=2, id="monitoreo")
scheduler.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))


