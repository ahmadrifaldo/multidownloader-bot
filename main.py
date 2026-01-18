import telebot
import yt_dlp
import os
import time
import requests
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from dotenv import load_dotenv

# --- KONFIGURASI ---
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID')) if os.getenv('ADMIN_ID') else 0
USER_FILE = "users.txt"

bot = telebot.TeleBot(TOKEN, threaded=True)
url_storage = {}

# --- DATABASE & CLEANUP ---
def add_user(user_id):
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, "w") as f: f.write("")
    with open(USER_FILE, "r") as f:
        users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USER_FILE, "a") as f: f.write(f"{user_id}\n")

def cleanup_garbage():
    extensions = (".mp3", ".mp4", ".webm", ".m4a", ".mkv", ".part", ".ytdl")
    for f in os.listdir('.'):
        if f.startswith(("file_", "tiktok_", "media_")) or f.endswith(extensions):
            try: os.remove(f)
            except: pass

# --- TIKTOK & INSTAGRAM HANDLER (API) ---
def download_tt_ig(url):
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        response = requests.get(api_url).json()
        if response.get('code') == 0:
            item = response['data']
            judul = item.get('title', 'Media')
            if 'images' in item and item['images']:
                return item['images'], judul, "foto"
            
            video_url = item['play']
            file_name = f"media_{os.urandom(3).hex()}.mp4"
            r = requests.get(video_url, stream=True)
            with open(file_name, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk: f.write(chunk)
            return file_name, judul, "video"
    except: pass
    return None, None, None

# --- CORE DOWNLOADER (YOUTUBE, IG, TT FALLBACK) ---
def download_media(link_key, mode='video'):
    # Ambil URL asli dari storage
    url = url_storage.get(link_key, link_key)
    if not url.startswith("http") and len(url) == 11:
        url = f"https://www.youtube.com/watch?v={url}"

    output_filename = f'file_{mode}_{os.urandom(3).hex()}'
    
    # Opsi yt-dlp untuk menembus proteksi terbaru
    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'ffmpeg_location': 'C:/ffmpeg/bin',
        'nocheckcertificate': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
    }

    # Gunakan cookies jika ada (PENTING untuk Instagram)
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    if mode == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'outtmpl': f'{output_filename}.%(ext)s',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 
            'outtmpl': f'{output_filename}.mp4',
        })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            judul = info.get('title', 'Media')
            actual_filename = f"{output_filename}.mp3" if mode == 'mp3' else f"{output_filename}.mp4"
            return actual_filename, judul, "done"
    except Exception as e:
        # Jika YouTube/IG via yt-dlp gagal, coba TikTok API jika itu link tiktok
        if "tiktok.com" in url:
            return download_tt_ig(url)
        return None, None, str(e)

# --- CALLBACK HANDLER ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        cleanup_garbage() 
        mode_code, link_key = call.data.split("|", 1)
        mode = 'video' if mode_code == 'vid' else 'mp3'
        
        wait = bot.send_message(call.message.chat.id, f"⏳ Memproses {mode.upper()}...")
        path_or_imgs, judul, status = download_media(link_key, mode)
        
        if status == "foto":
            imgs = [InputMediaPhoto(img) for img in path_or_imgs[:10]]
            bot.send_media_group(call.message.chat.id, imgs)
        elif path_or_imgs and os.path.exists(str(path_or_imgs)):
            if os.path.getsize(path_or_imgs) > 50 * 1024 * 1024:
                bot.send_message(call.message.chat.id, "⚠️ File terlalu besar (>50MB).")
            else:
                with open(path_or_imgs, 'rb') as f:
                    if mode == 'mp3': bot.send_audio(call.message.chat.id, f, caption=f"✅ {judul}")
                    else: bot.send_video(call.message.chat.id, f, caption=f"✅ {judul}")
            os.remove(path_or_imgs)
        else:
            bot.send_message(call.message.chat.id, "❌ Gagal mengunduh media.")
            
        bot.delete_message(call.message.chat.id, wait.message_id)
    except Exception as e:
        bot.send_message(call.message.chat.id, f"⚠️ Gagal: {str(e)[:100]}")

# --- MESSAGE HANDLER ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    add_user(message.chat.id)
    raw_text = message.text.strip()
    
    if raw_text.startswith("http"):
        if "youtube.com" in raw_text or "youtu.be" in raw_text:
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info = ydl.extract_info(raw_text, download=False)
                    link_key = info['id'] 
            except: link_key = raw_text
        else:
            # Gunakan Short Key untuk IG/TikTok agar aman di Callback Data
            short_key = os.urandom(4).hex()
            url_storage[short_key] = raw_text
            link_key = short_key

        markup = InlineKeyboardMarkup().row(
            InlineKeyboardButton("🎬 Video", callback_data=f"vid|{link_key}"),
            InlineKeyboardButton("🎵 MP3", callback_data=f"aud|{link_key}"))
        bot.reply_to(message, "Media terdeteksi! Pilih format:", reply_markup=markup)
    else:
        status = bot.reply_to(message, f"🔍 Mencari '{raw_text}'...")
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                res = ydl.extract_info(f"ytsearch1:{raw_text}", download=False)['entries'][0]
                link_key = res['id']
                markup = InlineKeyboardMarkup().row(
                    InlineKeyboardButton("🎬 Video", callback_data=f"vid|{link_key}"),
                    InlineKeyboardButton("🎵 MP3", callback_data=f"aud|{link_key}"))
                
                try:
                    bot.send_photo(message.chat.id, res.get('thumbnail'), caption=f"📺 **{res['title']}**", reply_markup=markup)
                    bot.delete_message(message.chat.id, status.message_id)
                except:
                    bot.edit_message_text(f"📺 **{res['title']}**", message.chat.id, status.message_id, reply_markup=markup)
        except: 
            try: bot.edit_message_text("❌ Tidak ditemukan.", message.chat.id, status.message_id)
            except: pass

if __name__ == "__main__":
    while True:
        try:
            print(">>> Bot Online & Secure...")
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            time.sleep(5)