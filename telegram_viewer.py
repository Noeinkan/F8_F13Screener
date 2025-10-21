"""
Telegram Message Viewer - Visualizzatore locale dei messaggi 13F
Mostra i messaggi come appaiono su Telegram in tempo reale
"""

import tkinter as tk
from tkinter import scrolledtext, ttk
import json
import time
import threading
import os
import webbrowser
from datetime import datetime
import re

class TelegramViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("📱 Telegram Message Viewer - 13F Alerts")
        self.root.geometry("800x600")
        self.root.configure(bg='#0e1621')
        
        # Header
        header = tk.Frame(root, bg='#17212b', height=50)
        header.pack(fill=tk.X)
        
        title = tk.Label(
            header, 
            text="🤖 13F Alert Bot",
            font=('Segoe UI', 14, 'bold'),
            bg='#17212b',
            fg='#ffffff'
        )
        title.pack(pady=10)
        
        # Bottoni controllo
        controls = tk.Frame(header, bg='#17212b')
        controls.pack(pady=5)
        
        load_btn = tk.Button(
            controls,
            text="📥 Carica Messaggi Precedenti",
            command=self.load_previous_messages,
            bg='#2ea043',
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            relief='flat',
            padx=10,
            pady=5,
            cursor='hand2'
        )
        load_btn.pack(side=tk.LEFT, padx=5)
        
        clear_btn = tk.Button(
            controls,
            text="🗑️ Pulisci Chat",
            command=self.clear_chat,
            bg='#da3633',
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            relief='flat',
            padx=10,
            pady=5,
            cursor='hand2'
        )
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        # Chat Area
        self.chat_frame = tk.Frame(root, bg='#0e1621')
        self.chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Canvas per scroll
        self.canvas = tk.Canvas(self.chat_frame, bg='#0e1621', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.chat_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg='#0e1621')
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Status bar
        self.status_bar = tk.Label(
            root,
            text="⏸️ In attesa di messaggi...",
            font=('Segoe UI', 9),
            bg='#17212b',
            fg='#8b949e',
            anchor='w',
            padx=10
        )
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        # Contatore messaggi
        self.message_count = 0
        self.loaded_previous = False
        
        # Avvia monitoraggio
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self.monitor_cache, daemon=True)
        self.monitor_thread.start()
    
    def load_previous_messages(self):
        """Carica tutti i messaggi precedenti dal file"""
        if self.loaded_previous:
            self.add_system_message("ℹ️ Messaggi precedenti già caricati!")
            return
        
        message_file = 'telegram_messages.json'
        if os.path.exists(message_file):
            try:
                with open(message_file, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                
                if messages:
                    self.add_system_message(f"📥 Caricamento di {len(messages)} messaggi precedenti...")
                    
                    # Carica messaggi velocemente (senza update tra ogni messaggio)
                    for msg in messages:
                        self.add_bot_message(msg['message'])
                    
                    # Update finale per velocità
                    self.canvas.update_idletasks()
                    self.canvas.yview_moveto(1.0)
                    
                    self.loaded_previous = True
                    self.add_system_message("✅ Caricamento completato!")
                else:
                    self.add_system_message("ℹ️ Nessun messaggio precedente trovato")
            except Exception as e:
                self.add_system_message(f"❌ Errore caricamento: {e}")
        else:
            self.add_system_message("ℹ️ Nessun file messaggi trovato")
    
    def clear_chat(self):
        """Pulisce la chat"""
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.message_count = 0
        self.loaded_previous = False
        self.status_bar.config(text="🗑️ Chat pulita")
        self.add_system_message("✨ Chat pulita! In attesa di nuovi messaggi...")
    
    def add_system_message(self, text):
        """Aggiunge un messaggio di sistema (grigio, centrato)"""
        msg_frame = tk.Frame(self.scrollable_frame, bg='#0e1621')
        msg_frame.pack(fill=tk.X, pady=5)
        
        msg = tk.Label(
            msg_frame,
            text=text,
            font=('Segoe UI', 9),
            bg='#1c2938',
            fg='#8b949e',
            wraplength=600,
            justify='center',
            padx=15,
            pady=10,
            relief='flat',
            borderwidth=0
        )
        msg.pack(anchor='center')
        
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)
    
    def parse_html_message(self, html_text):
        """Converte tag HTML in testo formattato"""
        # Rimuovi tag HTML ma mantieni la formattazione
        text = html_text.replace('<b>', '').replace('</b>', '')
        text = text.replace('<i>', '').replace('</i>', '')
        text = text.replace('<code>', '').replace('</code>', '')
        
        # Gestisci link
        link_pattern = r'<a href=["\']([^"\']+)["\']>([^<]+)</a>'
        text = re.sub(link_pattern, r'\2\n🔗 \1', text)
        
        return text
    
    def make_links_clickable(self, text_widget, text):
        """Rende i link cliccabili nel Text widget"""
        # Trova tutti gli URL nel testo
        url_pattern = r'https?://[^\s\n]+'
        
        for match in re.finditer(url_pattern, text):
            url = match.group()
            start_pos = f"1.0+{match.start()}c"
            end_pos = f"1.0+{match.end()}c"
            
            # Colora il link
            text_widget.tag_add(url, start_pos, end_pos)
            text_widget.tag_config(url, foreground='#58a6ff', underline=True)
            text_widget.tag_bind(url, '<Button-1>', lambda e, link=url: webbrowser.open(link))
            text_widget.tag_bind(url, '<Enter>', lambda e: text_widget.config(cursor='hand2'))
            text_widget.tag_bind(url, '<Leave>', lambda e: text_widget.config(cursor='arrow'))
    
    def add_bot_message(self, html_message):
        """Aggiunge un messaggio del bot (stile Telegram)"""
        self.message_count += 1
        
        # Frame principale
        msg_frame = tk.Frame(self.scrollable_frame, bg='#0e1621')
        msg_frame.pack(fill=tk.X, pady=8, padx=10)
        
        # Bubble del messaggio (stile Telegram - verde chiaro)
        bubble = tk.Frame(msg_frame, bg='#2b5278', relief='flat', borderwidth=0)
        bubble.pack(anchor='w', padx=(50, 150))
        
        # Converti HTML in testo
        clean_text = self.parse_html_message(html_message)
        
        # Contenuto del messaggio - USA TEXT WIDGET (selezionabile!)
        msg_content = tk.Text(
            bubble,
            font=('Segoe UI', 10),
            bg='#2b5278',
            fg='#ffffff',
            wrap='word',
            width=60,
            height=clean_text.count('\n') + 2,
            padx=12,
            pady=8,
            relief='flat',
            borderwidth=0,
            cursor='arrow',
            exportselection=True
        )
        msg_content.insert('1.0', clean_text)
        msg_content.config(state='disabled')  # Readonly ma selezionabile
        msg_content.pack()
        
        # Trova e rendi cliccabili i link
        self.make_links_clickable(msg_content, clean_text)
        
        # Timestamp
        timestamp = datetime.now().strftime('%H:%M')
        time_label = tk.Label(
            bubble,
            text=timestamp,
            font=('Segoe UI', 8),
            bg='#2b5278',
            fg='#a0a0a0',
            padx=12,
            pady=(0, 5)
        )
        time_label.pack(anchor='e')
        
        # Aggiorna scroll
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)
        
        # Aggiorna status
        self.status_bar.config(
            text=f"✅ Messaggi ricevuti: {self.message_count} | Ultimo: {timestamp}"
        )
    
    def monitor_cache(self):
        """Monitora il file cache per nuovi messaggi"""
        message_file = 'telegram_messages.json'
        last_count = 0
        shown_welcome = False
        
        # Attendi un attimo per permettere al programma di inizializzare
        time.sleep(2)
        
        # Controlla se ci sono già messaggi
        if os.path.exists(message_file):
            try:
                with open(message_file, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                    last_count = len(messages)
                    if last_count > 0:
                        self.add_system_message(
                            f"💾 Trovati {last_count} messaggi precedenti.\n"
                            f"Clicca '📥 Carica Messaggi Precedenti' per visualizzarli.\n\n"
                            f"⏳ In attesa di nuovi Form 13F live..."
                        )
                        shown_welcome = True
            except:
                pass
        
        while self.monitoring:
            try:
                # Leggi messaggi salvati
                if os.path.exists(message_file):
                    with open(message_file, 'r', encoding='utf-8') as f:
                        messages = json.load(f)
                        current_count = len(messages)
                        
                        # Mostra SOLO i nuovi messaggi (live)
                        if current_count > last_count:
                            # Aggiungi tutti i nuovi messaggi velocemente
                            new_messages = messages[last_count:]
                            for msg in new_messages:
                                self.add_bot_message(msg['message'])
                            
                            # Un solo system message alla fine invece di uno per messaggio
                            if len(new_messages) == 1:
                                self.add_system_message(
                                    f"✅ Nuovo filing! Filer: {new_messages[0].get('filer', 'N/A')}"
                                )
                            else:
                                self.add_system_message(
                                    f"✅ {len(new_messages)} nuovi filing rilevati!"
                                )
                            
                            # Update finale per velocità
                            self.canvas.update_idletasks()
                            self.canvas.yview_moveto(1.0)
                            
                            last_count = current_count
                        elif not shown_welcome:
                            self.add_system_message(
                                "⏳ In attesa di nuovi Form 13F...\n"
                                "Il programma principale sta monitorando il feed SEC."
                            )
                            shown_welcome = True
                else:
                    # File non esiste ancora
                    if not shown_welcome:
                        time.sleep(3)
                        if not os.path.exists(message_file):
                            self.add_system_message(
                                "⏳ In attesa del primo Form 13F...\n"
                                "Il file messaggi verrà creato al primo filing rilevato."
                            )
                        shown_welcome = True
                
                time.sleep(0.5)  # Controlla ogni mezzo secondo (più veloce!)
                
            except Exception as e:
                print(f"Errore monitoraggio: {e}")
                time.sleep(5)

def main():
    root = tk.Tk()
    app = TelegramViewer(root)
    
    # Gestisci chiusura
    def on_closing():
        app.monitoring = False
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == '__main__':
    main()
