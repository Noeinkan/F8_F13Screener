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
import sys
import psutil  # Per gestire processi

class SingleInstanceChecker:
    """Controlla che ci sia solo un'istanza del viewer attiva"""
    def __init__(self):
        self.lockfile = 'telegram_viewer.lock'
        self.pid = os.getpid()
        
    def is_already_running(self):
        """Controlla se c'è già un'istanza in esecuzione"""
        if os.path.exists(self.lockfile):
            try:
                with open(self.lockfile, 'r') as f:
                    old_pid = int(f.read().strip())
                
                # Controlla se il processo esiste ancora
                if psutil.pid_exists(old_pid):
                    try:
                        proc = psutil.Process(old_pid)
                        # Verifica che sia davvero python/telegram_viewer
                        if 'python' in proc.name().lower():
                            print(f"[INFO] Trovata istanza precedente (PID {old_pid}), chiusura in corso...")
                            proc.terminate()  # Termina gentilmente
                            proc.wait(timeout=3)  # Aspetta max 3 secondi
                            print(f"[INFO] Istanza precedente chiusa")
                    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                        pass
                
                # Rimuovi il vecchio lockfile
                os.remove(self.lockfile)
            except (ValueError, FileNotFoundError):
                pass
        
        return False
    
    def create_lock(self):
        """Crea il file di lock con il PID corrente"""
        try:
            with open(self.lockfile, 'w') as f:
                f.write(str(self.pid))
            return True
        except Exception as e:
            print(f"[ERROR] Impossibile creare lockfile: {e}")
            return False
    
    def release_lock(self):
        """Rimuove il file di lock"""
        try:
            if os.path.exists(self.lockfile):
                os.remove(self.lockfile)
        except Exception as e:
            print(f"[ERROR] Impossibile rimuovere lockfile: {e}")

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
                    
                    # Carica messaggi SENZA aggiornare UI ad ogni messaggio (velocità massima)
                    for msg in messages:
                        self.add_bot_message(msg['message'], update_ui=False)
                    
                    # UN SOLO update finale - ISTANTANEO
                    self.canvas.update_idletasks()
                    self.canvas.yview_moveto(1.0)
                    timestamp = datetime.now().strftime('%H:%M')
                    self.status_bar.config(
                        text=f"✅ Messaggi ricevuti: {self.message_count} | Ultimo: {timestamp}"
                    )
                    
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
    
    def add_bot_message(self, html_message, update_ui=True):
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
            padx=12
        )
        time_label.pack(anchor='e', pady=(0, 5))
        
        # Aggiorna SOLO se richiesto (evita update ripetuti durante caricamento batch)
        if update_ui:
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
        auto_loaded = False  # Flag per auto-caricamento iniziale
        
        print(f"[DEBUG] Monitor thread avviato, cercando file: {os.path.abspath(message_file)}")
        
        # Attendi un attimo per permettere al programma di inizializzare
        time.sleep(1)
        
        # CARICA AUTOMATICAMENTE TUTTI I MESSAGGI ALL'AVVIO - VELOCITÀ MASSIMA
        if os.path.exists(message_file):
            try:
                with open(message_file, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                    message_count = len(messages)
                    print(f"[DEBUG] Trovati {message_count} messaggi esistenti - CARICAMENTO ISTANTANEO")
                    
                    if message_count > 0:
                        # Mostra messaggio di caricamento
                        self.add_system_message(f"📥 Caricamento di {message_count} messaggi da Telegram...")
                        
                        # Carica TUTTI i messaggi SENZA aggiornare UI (velocità massima)
                        for msg in messages:
                            self.add_bot_message(msg['message'], update_ui=False)
                        
                        # UN SOLO update finale - ISTANTANEO
                        self.canvas.update_idletasks()
                        self.canvas.yview_moveto(1.0)
                        timestamp = datetime.now().strftime('%H:%M')
                        self.status_bar.config(
                            text=f"✅ Messaggi ricevuti: {self.message_count} | Ultimo: {timestamp}"
                        )
                        
                        # Messaggio di completamento
                        self.add_system_message(
                            f"✅ {message_count} messaggi caricati!\n"
                            f"⏳ In attesa di nuovi Form 13F live..."
                        )
                        
                        last_count = message_count
                        auto_loaded = True
                        shown_welcome = True
                        self.loaded_previous = True  # Marca come già caricati
                        
            except Exception as e:
                print(f"[DEBUG] Errore caricamento automatico: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"[DEBUG] File messaggi non esiste ancora")
            self.add_system_message(
                "⏳ In attesa del primo Form 13F...\n"
                "Il file messaggi verrà creato al primo filing rilevato."
            )
            shown_welcome = True
        
        # Loop di monitoraggio per NUOVI messaggi - VELOCITÀ MASSIMA
        while self.monitoring:
            try:
                # Leggi messaggi salvati
                if os.path.exists(message_file):
                    try:
                        with open(message_file, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                            if content:  # Solo se il file non è vuoto
                                messages = json.loads(content)
                            else:
                                messages = []
                    except (json.JSONDecodeError, ValueError) as e:
                        # File corrotto, ignora e aspetta nuovi messaggi
                        print(f"[DEBUG] Errore parsing JSON: {e}")
                        messages = []
                    
                    current_count = len(messages)
                    
                    # Mostra SOLO i nuovi messaggi (dopo il caricamento iniziale)
                    if current_count > last_count:
                        print(f"[DEBUG] Nuovi messaggi LIVE: {current_count - last_count}")
                        # Aggiungi tutti i nuovi messaggi SENZA update intermedi
                        new_messages = messages[last_count:]
                        for msg in new_messages:
                            self.add_bot_message(msg['message'], update_ui=False)
                        
                        # UN SOLO update finale - ISTANTANEO
                        self.canvas.update_idletasks()
                        self.canvas.yview_moveto(1.0)
                        timestamp = datetime.now().strftime('%H:%M')
                        self.status_bar.config(
                            text=f"✅ Messaggi ricevuti: {self.message_count} | Ultimo: {timestamp}"
                        )
                        
                        # Un solo system message alla fine
                        if len(new_messages) == 1:
                            self.add_system_message(
                                f"✅ Nuovo filing! Filer: {new_messages[0].get('filer', 'N/A')}"
                            )
                        else:
                            self.add_system_message(
                                f"✅ {len(new_messages)} nuovi filing rilevati!"
                            )
                        
                        last_count = current_count
                
                time.sleep(0.5)  # Controlla ogni mezzo secondo
                
            except Exception as e:
                print(f"[DEBUG] Errore monitoraggio: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(5)

def main():
    # Controlla istanza singola
    instance_checker = SingleInstanceChecker()
    
    # Chiudi eventuali istanze precedenti
    instance_checker.is_already_running()
    
    # Crea il lock per questa istanza
    if not instance_checker.create_lock():
        print("[ERROR] Impossibile creare lock, uscita...")
        return
    
    try:
        root = tk.Tk()
        app = TelegramViewer(root)
        
        # Gestisci chiusura
        def on_closing():
            app.monitoring = False
            instance_checker.release_lock()  # Rilascia il lock
            root.destroy()
        
        root.protocol("WM_DELETE_WINDOW", on_closing)
        root.mainloop()
    except Exception as e:
        # Mostra errore in una finestra di dialogo se Tk fallisce
        import traceback
        error_msg = f"Errore avvio Telegram Viewer:\n{str(e)}\n\n{traceback.format_exc()}"
        
        # Prova a mostrare con messagebox
        try:
            import tkinter.messagebox as messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Errore Telegram Viewer", error_msg)
        except:
            # Fallback: scrivi su file
            with open('telegram_viewer_error.log', 'w') as f:
                f.write(error_msg)
            print(error_msg)
    finally:
        # Assicurati di rilasciare il lock anche in caso di errore
        instance_checker.release_lock()

if __name__ == '__main__':
    main()
