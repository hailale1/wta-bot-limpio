def get_active_wta_tournaments():
    # URL oficial de la API v4 para listar deportes
    url = "https://the-odds-api.com"
    params = {'apiKey': ODDS_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        
        # Validación de código de estado antes de intentar parsear JSON
        if r.status_code != 200:
            logging.error(f"Error API: Código {r.status_code}. Respuesta no es JSON válido.")
            return []
            
        # Extrae los torneos de tenis WTA activos
        return [s['key'] for s in r.json() if 'tennis_wta' in s['key']]
        
    except Exception as e:
        logging.error(f"Error conectando para obtener torneos: {e}")
        return []

def fetch_single_match_odds(sport_key, match_id, p1, p2):
    # Endpoint correcto v4 para obtener cuotas (odds) de un deporte específico
    url = f"https://the-odds-api.com/{sport_key}/odds/"
    params = {
        'apiKey': ODDS_API_KEY, 
        'regions': 'eu', 
        'markets': 'h2h'
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        
        if r.status_code != 200:
            logging.error(f"Error API Pre-partido: Código {r.status_code}")
            return

        for m in r.json():
            if m.get('id') == match_id:
                bookmakers = m.get('bookmakers', [])
                p1_odds, p2_odds = None, None
                
                if bookmakers and len(bookmakers) > 0:
                    for bookmaker in bookmakers:
                        markets = bookmaker.get('markets', [])
                        if markets and len(markets) > 0:
                            # CORRECCIÓN IMPORTANTE: markets es una LISTA en la v4 API, iteramos sobre ella
                            for market in markets:
                                if market.get('key') == 'h2h':
                                    for o in market.get('outcomes', []):
                                        if o.get('name') == p1: p1_odds = o.get('price')
                                        elif o.get('name') == p2: p2_odds = o.get('price')
                            break # Rompe tras el primer bookmaker procesado exitosamente
                
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
        # Endpoint correcto v4
        url = f"https://the-odds-api.com/{sport_key}/odds/"
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
        # Endpoint correcto v4
        url = f"https://the-odds-api.com/{sport_key}/odds/"
        # NOTA: Para capturar partidos "en vivo", The Odds API suele requerir parámetros adicionales o revisar eventos en curso según tu plan.
        params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                continue
                
            for match in r.json():
                match_id = match.get('id')
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute("SELECT tournament, player_1, player_2, fav_name, fav_pre_odds FROM wta_matches WHERE match_id=?", (match_id,))
                db_data = cursor.fetchone()
                conn.close()
                
                # ... (El resto de tu lógica para analizar las cuotas en vivo va aquí debajo)
        except Exception as e:
            logging.error(f"Error monitoreando partidos en vivo: {e}")

# --- CORRECCIÓN EN LAS URLS DE TELEGRAM ---
def send_startup_test_message():
    # URL oficial de la API de bots de Telegram
    url = f"https://telegram.org{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "<b>✅ Bot WTA Iniciado Correctamente</b>\nEl sistema se ha conectado utilizando las rutas oficiales de la API.",
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            logging.info("🚀 ¡Mensaje de prueba enviado con éxito a Telegram!")
        else:
            logging.error(f"❌ Falló mensaje de prueba. Código: {r.status_code} - Info: {r.text}")
    except Exception as e:
        logging.error(f"❌ Error de conexión con Telegram en inicio: {e}")
