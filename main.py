import telebot
import yt_dlp
import os
import time
import requests
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from dotenv import load_dotenv # Tambahkan ini

# --- KONFIGURASI AMAN ---
# --- KONFIGURASI AMAN ---
load_dotenv()  # PASTIKAN TULISANNYA dotenv (pake 't', bukan 'l')
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID')) if os.getenv('ADMIN_ID') else 0
USER_FILE = "users.txt"

bot = telebot.TeleBot(TOKEN, threaded=True)

# PENYIMPANAN LINK SEMENTARA
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

# --- TIKTOK & INSTAGRAM ---
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

# --- DOWNLOAD UTAMA ---
# --- DOWNLOAD UTAMA (Optimasi Kualitas agar tidak lewat 50MB) ---
def download_media(url_or_id, mode='video'):
    if url_or_id.startswith("http"):
        if "tiktok.com" in url_or_id or "instagram.com" in url_or_id:
            return download_tt_ig(url_or_id)
        url = url_or_id
    else:
        url = f"https://www.youtube.com/watch?v={url_or_id}"

    output_filename = f'file_{mode}_{os.urandom(3).hex()}'
    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'ffmpeg_location': 'C:/ffmpeg/bin',
    }

    if mode == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'outtmpl': f'{output_filename}.%(ext)s',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        })
    else:
        # DIBATASI ke 720p agar file tidak meledak ukurannya (batas bot 50MB)
        ydl_opts.update({
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 
            'outtmpl': f'{output_filename}.mp4',
        })
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        judul = info.get('title', 'Media')
        actual_filename = f"{output_filename}.mp3" if mode == 'mp3' else f"{output_filename}.mp4"
        return actual_filename, judul, "done"

# --- CALLBACK ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        # Bersihkan sampah lama setiap kali ada permintaan baru
        cleanup_garbage() 
        
        mode_code, link_key = call.data.split("|", 1)
        real_url = url_storage.get(link_key)
        
        if not real_url:
            if len(link_key) == 11:
                real_url = link_key
            else:
                return bot.answer_callback_query(call.id, "❌ Link Kadaluarsa.", show_alert=True)

        mode = 'video' if mode_code == 'vid' else 'mp3'
        wait = bot.send_message(call.message.chat.id, f"⏳ Memproses {mode.upper()}...")
        
        path_or_imgs, judul, status = download_media(real_url, mode)
        
        if status == "foto":
            imgs = [InputMediaPhoto(img) for img in path_or_imgs[:10]]
            bot.send_media_group(call.message.chat.id, imgs)
        elif path_or_imgs and os.path.exists(str(path_or_imgs)):
            # Cek ukuran file sebelum kirim (Batas Telegram Bot 50MB)
            if os.path.getsize(path_or_imgs) > 50 * 1024 * 1024:
                bot.send_message(call.message.chat.id, "⚠️ File terlalu besar (>50MB). Tidak bisa dikirim via Telegram.")
            else:
                with open(path_or_imgs, 'rb') as f:
                    if mode == 'mp3': bot.send_audio(call.message.chat.id, f, caption=f"✅ {judul}")
                    else: bot.send_video(call.message.chat.id, f, caption=f"✅ {judul}")
            os.remove(path_or_imgs)
        
        bot.delete_message(call.message.chat.id, wait.message_id)
    except Exception as e:
        bot.send_message(call.message.chat.id, f"⚠️ Gagal: {str(e)[:100]}")
        cleanup_garbage() # Cleanup jika terjadi error tengah jalan

# --- PESAN MASUK ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    add_user(message.chat.id)
    raw_text = message.text.strip()
    
    if raw_text.startswith("http"):
        link_key = raw_text
        
        # Jika link Youtube, ambil ID-nya (karena ID pendek & permanen)
        if "youtube.com" in raw_text or "youtu.be" in raw_text:
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info = ydl.extract_info(raw_text, download=False)
                    link_key = info['id'] 
            except: pass
        else:
            # Jika link TikTok/IG (panjang), simpan di storage & gunakan Key pendek
            short_key = os.urandom(4).hex()
            url_storage[short_key] = raw_text
            link_key = short_key

        markup = InlineKeyboardMarkup().row(
            InlineKeyboardButton("🎬 Video", callback_data=f"vid|{link_key}"),
            InlineKeyboardButton("🎵 MP3", callback_data=f"aud|{link_key}"))
        bot.reply_to(message, "Link terdeteksi! Pilih format:", reply_markup=markup)
    else:
        status = bot.reply_to(message, f"🔍 Mencari '{raw_text}'...")
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                res = ydl.extract_info(f"ytsearch1:{raw_text}", download=False)['entries'][0]
                link_key = res['id']
                markup = InlineKeyboardMarkup().row(
                    InlineKeyboardButton("🎬 Video", callback_data=f"vid|{link_key}"),
                    InlineKeyboardButton("🎵 MP3", callback_data=f"aud|{link_key}"))
                bot.delete_message(message.chat.id, status.message_id)
                bot.send_photo(message.chat.id, res.get('thumbnail'), caption=f"📺 **{res['title']}**", reply_markup=markup)
        except: bot.edit_message_text("❌ Tidak ditemukan.", message.chat.id, status.message_id)

if __name__ == "__main__":
    print(">>> Bot v3.0 Online (Fix Button Data Invalid)...")
    cleanup_garbage()
    bot.infinity_polling()