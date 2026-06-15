# Laporan Teknis: Cara Kerja MARK-XX (Personal AI Assistant)

MARK-XX adalah asisten AI personal bergaya "Jarvis" yang dirancang untuk berjalan secara lokal di komputer pengguna. Sistem ini mengintegrasikan kecerdasan buatan dari Google Gemini dengan kontrol sistem operasi, pengenalan suara, dan memori persisten.

Berikut adalah penjelasan mendalam mengenai cara kerjanya:

---

## 1. Arsitektur Utama: Siklus ReAct (Observe → Think → Act)
Inti dari MARK-XX adalah sebuah **Agentic Planner** yang menggunakan pola ReAct. Alih-alih hanya memberikan jawaban teks, asisten ini bisa "berpikir" dan "bertindak" menggunakan alat (tools) yang tersedia.

*   **THINK (Berpikir):** Saat menerima perintah, LLM (Gemini) menganalisis tugas tersebut dan menentukan apakah ia perlu melakukan aksi (seperti membuka aplikasi atau mencari di web).
*   **ACT (Bertindak):** Jika perlu aksi, MARK akan memanggil fungsi spesifik (TOOL_CALL) dalam format JSON.
*   **OBSERVE (Mengamati):** Hasil dari aksi tersebut dikembalikan ke LLM sebagai input baru. MARK melihat hasilnya, lalu memutuskan langkah selanjutnya sampai tugas selesai.

---

## 2. Komponen Inti (Core Modules)

### A. Otak AI (Gemini LLM)
MARK-XX menggunakan API Google Gemini (biasanya model Flash atau Pro).
- **Key Rotation:** Sistem mendukung penggunaan beberapa API Key secara bergantian untuk menghindari batasan kuota (rate limits).
- **Context Awareness:** Sistem menyuntikkan profil pengguna dan instruksi khusus dari file `GEMINI.md` ke dalam setiap percakapan agar asisten terasa lebih personal.

### B. Input & Output Suara (STT & TTS)
- **Speech-to-Text (STT):** Menggunakan library `faster-whisper` untuk mengubah suara pengguna menjadi teks secara lokal dan cepat.
- **Text-to-Speech (TTS):** Menggunakan `edge-tts` untuk menghasilkan suara asisten yang terdengar alami (neural voices).

### C. Memori Persisten (SQLite & Files)
- **Database:** Riwayat percakapan dan preferensi disimpan dalam database SQLite (`markxx.db`).
- **Knowledge Base:** MARK-XX dapat membaca file lokal untuk memahami konteks proyek atau preferensi jangka panjang pengguna.

### D. Penglihatan (Vision)
- **Screenshot:** MARK dapat mengambil gambar layar saat ini untuk menganalisis apa yang sedang dikerjakan pengguna.
- **Webcam:** Dapat mengakses kamera untuk interaksi visual secara langsung.

---

## 3. Sistem Aksi (Tools & Actions)
MARK-XX memiliki "tangan" untuk berinteraksi dengan komputer melalui berbagai modul di direktori `actions/`:

1.  **Computer Control:** Menjalankan perintah PowerShell/Terminal, membuka aplikasi, dan mengetik teks.
2.  **File Manager:** Membuat, membaca, memindahkan, dan menghapus file/folder.
3.  **File Analysis:** Menganalisis dokumen PDF, gambar, atau file kode menggunakan kemampuan multimodal Gemini.
4.  **Web Search:** Melakukan pencarian di internet untuk mendapatkan informasi terbaru.

---

## 4. Alur Kerja (Workflow) Contoh
Misalkan Anda berkata: *"Buka Notepad dan tulis daftar belanja: apel, susu, roti."*

1.  **Input:** Suara Anda ditangkap mic → `stt.py` mengubahnya jadi teks.
2.  **Plan:** `planner.py` mengirim teks ke Gemini. Gemini membalas dengan `TOOL_CALL` untuk `open_app("notepad")`.
3.  **Action 1:** Sistem membuka Notepad.
4.  **Observation 1:** Sistem melaporkan "Notepad berhasil dibuka".
5.  **Plan 2:** Gemini mengirim `TOOL_CALL` untuk `type_text("daftar belanja: apel, susu, roti")`.
6.  **Action 2:** Sistem mengetikkan teks tersebut secara otomatis.
7.  **Final Response:** MARK-XX menjawab via suara (`tts.py`): *"Selesai! Saya sudah membuka Notepad dan menuliskan daftar belanja Anda."*

---

## 5. Antarmuka Pengguna (UI)
Asisten ini menggunakan **PyQt6** dengan desain *Glassmorphism* yang modern (transparan dan bisa digeser). UI ini berfungsi sebagai jembatan antara pengguna dan logika agen di belakangnya, menampilkan proses berpikir (thinking steps) dan status aksi yang sedang dijalankan.

---

**Kesimpulan:**
MARK-XX bukan sekadar chatbot, melainkan sebuah **Agen AI** yang memiliki otonomi untuk menggunakan komputer sebagai alat guna menyelesaikan tugas yang diberikan oleh pengguna.
