import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import hashlib
import json
import os
import datetime

# ================== KONFIGURASI ==================
NAMA_TOKO, ALAMAT_TOKO = "Toko Kelontong Ghattan", "Jl. Raya No. 1"
DB_FILE = "toko_ghattan.db"
FOLDER_STRUK, FOLDER_LAPORAN = "struk", "laporan"
FMT_WAKTU = "%Y-%m-%d %H:%M:%S"
JSON_PRODUK, JSON_TRX = "produk_ghattan.json", "transaksi_ghattan.json"  # diimpor sekali jika ada
AKUN_AWAL = {"kasir": ("123", "Kasir"), "admin": ("456", "Admin")}  # username: (password, peran)
PERIODE = ["Hari Ini", "7 Hari Terakhir", "Bulan Ini", "Semua"]

MERAH, MERAH_TUA, PUTIH, ABU = "#C62828", "#8E0000", "#FFFFFF", "#F5F5F5"
HIJAU, ABU_TOMBOL = "#1B5E20", "#616161"
PRODUK_AWAL = [  # (kode, nama, harga_beli, harga_jual, stok)
    ("1", "Beras 5 Kg", 85000, 97000, 20),
    ("2", "Gula 1 Kg", 17000, 20000, 35),
    ("3", "Minyak Goreng 1 Liter", 20000, 25000, 50),
    ("4", "Mie Instan", 3000, 4000, 80),
]

FILTER_PERIODE = {  # {k} = nama kolom waktu
    "Hari Ini": "date({k}) = date('now', 'localtime')",
    "7 Hari Terakhir": "date({k}) > date('now', 'localtime', '-7 days')",
    "Bulan Ini": "strftime('%Y-%m', {k}) = strftime('%Y-%m', 'now', 'localtime')",
    "Semua": "1 = 1",
}

# nama & harga disalin ke transaksi_item agar riwayat tetap utuh walau produk diubah/dihapus
SKEMA = """
CREATE TABLE IF NOT EXISTS pengguna (username TEXT PRIMARY KEY, password TEXT NOT NULL, peran TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS produk (
    kode TEXT PRIMARY KEY, nama TEXT NOT NULL,
    harga_beli INTEGER NOT NULL CHECK (harga_beli >= 0),
    harga_jual INTEGER NOT NULL CHECK (harga_jual >= 0),
    stok INTEGER NOT NULL CHECK (stok >= 0));
CREATE TABLE IF NOT EXISTS transaksi (
    no INTEGER PRIMARY KEY AUTOINCREMENT, waktu TEXT NOT NULL, kasir TEXT NOT NULL,
    total INTEGER NOT NULL, bayar INTEGER NOT NULL, kembali INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS transaksi_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    no_transaksi INTEGER NOT NULL REFERENCES transaksi(no) ON DELETE CASCADE,
    kode TEXT NOT NULL, nama TEXT NOT NULL, qty INTEGER NOT NULL,
    harga_beli INTEGER NOT NULL, harga_jual INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_transaksi_waktu ON transaksi(waktu);
CREATE INDEX IF NOT EXISTS idx_item_transaksi ON transaksi_item(no_transaksi);
"""
SQL_ITEM = "INSERT INTO transaksi_item (no_transaksi, kode, nama, qty, harga_beli, harga_jual) VALUES (?, ?, ?, ?, ?, ?)"


def rp(angka):
    return "Rp {:,.0f}".format(angka).replace(",", ".")


def hash_password(teks):
    return hashlib.sha256(teks.encode("utf-8")).hexdigest()


def muat_json(file):
    if not os.path.exists(file):
        return []
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)


def buat_tabel(parent, kolom, **kw):  # Buat Treeview. kolom = [(id, judul, lebar), ...]; kolom 'nama' rata kiri.
    tv = ttk.Treeview(parent, columns=[k[0] for k in kolom], show="headings", **kw)
    for c, t, w in kolom:
        tv.heading(c, text=t)
        tv.column(c, width=w, anchor="w" if c == "nama" else "center")
    return tv


# ================== DATABASE SQLITE ==================
class Database:
    def __init__(self, file=DB_FILE):
        baru = not os.path.exists(file)
        self.conn = sqlite3.connect(file)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        with self.conn:
            self.conn.executescript(SKEMA)
        if baru:
            self.isi_awal()

    def q(self, sql, *args):
        return self.conn.execute(sql, args)

    def isi_awal(self):  # Hanya dipanggil saat file database baru dibuat.
        with self.conn:
            self.conn.executemany("INSERT INTO pengguna VALUES (?, ?, ?)",
                                  [(u, hash_password(p), r) for u, (p, r) in AKUN_AWAL.items()])
        if not self.impor_json():
            with self.conn:
                self.conn.executemany("INSERT INTO produk VALUES (?, ?, ?, ?, ?)", PRODUK_AWAL)

    def impor_json(self):  # Pindahkan data dari file JSON versi lama (jika ada).
        if not os.path.exists(JSON_PRODUK):
            return False
        try:
            produk, transaksi = muat_json(JSON_PRODUK), muat_json(JSON_TRX)
            with self.conn:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO produk VALUES (?, ?, ?, ?, ?)",
                    [(str(p["kode"]), p["nama"], p["harga_beli"], p["harga_jual"], p["stok"])
                     for p in produk])
                for t in transaksi:
                    self.q("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?)", t["no"], t["waktu"],
                           t["kasir"], t["total"], t["bayar"], t["kembali"])
                    self.conn.executemany(SQL_ITEM, [
                        (t["no"], str(i["kode"]), i["nama"], i["qty"], i["harga_beli"], i["harga_jual"])
                        for i in t["items"]])
            return True
        except Exception:
            return False

    def cek_login(self, username, password):  # Mengembalikan peran ('Admin'/'Kasir') jika cocok, selain itu None.
        r = self.q("SELECT peran FROM pengguna WHERE username = ? AND password = ?",
                   username, hash_password(password)).fetchone()
        return r["peran"] if r else None

    def daftar_produk(self, kata=""):
        like = "%" + kata.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return self.q("SELECT * FROM produk WHERE nama LIKE ? ESCAPE '\\' OR kode LIKE ? ESCAPE '\\' "
                      "ORDER BY CAST(kode AS INTEGER), kode", like, like).fetchall()

    def ambil_produk(self, kode):
        return self.q("SELECT * FROM produk WHERE kode = ?", kode).fetchone()

    def simpan_produk(self, kode, nama, beli, jual, stok):  # Tambah baru, atau update jika kode sudah ada.
        with self.conn:
            self.q("INSERT INTO produk VALUES (?, ?, ?, ?, ?) ON CONFLICT(kode) DO UPDATE SET "
                   "nama = excluded.nama, harga_beli = excluded.harga_beli, "
                   "harga_jual = excluded.harga_jual, stok = excluded.stok",
                   kode, nama, beli, jual, stok)

    def hapus_produk(self, kode):
        with self.conn:
            self.q("DELETE FROM produk WHERE kode = ?", kode)

    def kode_berikutnya(self):
        r = self.q("SELECT MAX(CAST(kode AS INTEGER)) AS m FROM produk "
                   "WHERE kode NOT GLOB '*[^0-9]*'").fetchone()
        return str((r["m"] or 0) + 1)

    def simpan_transaksi(self, kasir, keranjang, bayar, waktu):
        """Simpan transaksi + kurangi stok dalam satu transaksi database; gagal = rollback.
        Mengembalikan (no, total, kembali, items)."""
        with self.conn:
            items, total = [], 0
            for kode, qty in keranjang.items():
                p = self.ambil_produk(kode)
                if p is None:
                    raise ValueError(f"Barang kode {kode} sudah tidak ada.")
                cur = self.q("UPDATE produk SET stok = stok - ? WHERE kode = ? AND stok >= ?",
                             qty, kode, qty)
                if cur.rowcount == 0:
                    raise ValueError(f"Stok {p['nama']} tidak cukup (sisa {p['stok']}).")
                items.append({"kode": p["kode"], "nama": p["nama"], "qty": qty,
                              "harga_beli": p["harga_beli"], "harga_jual": p["harga_jual"]})
                total += p["harga_jual"] * qty
            if bayar < total:
                raise ValueError("Uang bayar kurang!")
            kembali = bayar - total
            no = self.q("INSERT INTO transaksi (waktu, kasir, total, bayar, kembali) "
                        "VALUES (?, ?, ?, ?, ?)", waktu.strftime(FMT_WAKTU), kasir, total,
                        bayar, kembali).lastrowid
            self.conn.executemany(SQL_ITEM, [
                (no, i["kode"], i["nama"], i["qty"], i["harga_beli"], i["harga_jual"])
                for i in items])
        return no, total, kembali, items

    @staticmethod
    def _filter(periode, kolom):
        return FILTER_PERIODE.get(periode, "1 = 1").format(k=kolom)

    def daftar_transaksi(self, periode):
        return self.q(f"""
            SELECT t.no, t.waktu, t.kasir, t.total, t.bayar, t.kembali,
                   COALESCE(SUM(i.qty), 0) AS jml,
                   COALESCE(SUM((i.harga_jual - i.harga_beli) * i.qty), 0) AS laba
            FROM transaksi t LEFT JOIN transaksi_item i ON i.no_transaksi = t.no
            WHERE {self._filter(periode, 't.waktu')}
            GROUP BY t.no ORDER BY t.no DESC""").fetchall()

    def item_transaksi(self, no):
        return self.q("SELECT * FROM transaksi_item WHERE no_transaksi = ? ORDER BY id", no).fetchall()

    def laporan(self, periode):
        w = self._filter(periode, "t.waktu")
        gabung = "FROM transaksi_item i JOIN transaksi t ON t.no = i.no_transaksi"
        trx = self.q(f"SELECT COUNT(*) AS n, COALESCE(SUM(t.total), 0) AS pendapatan "
                     f"FROM transaksi t WHERE {w}").fetchone()
        itm = self.q(f"SELECT COALESCE(SUM(i.qty), 0) AS qty, "
                     f"COALESCE(SUM(i.harga_beli * i.qty), 0) AS modal {gabung} WHERE {w}").fetchone()
        per_produk = self.q(f"""
            SELECT i.kode, MAX(i.nama) AS nama, SUM(i.qty) AS qty,
                   SUM(i.harga_jual * i.qty) AS pendapatan,
                   SUM((i.harga_jual - i.harga_beli) * i.qty) AS laba
            {gabung} WHERE {w} GROUP BY i.kode ORDER BY qty DESC, nama""").fetchall()
        return {"jumlah": trx["n"], "pendapatan": trx["pendapatan"], "qty": itm["qty"],
                "modal": itm["modal"], "per_produk": per_produk}


# ================== APLIKASI ==================
class Aplikasi:
    def __init__(self, root):
        self.root = root
        root.title(NAMA_TOKO)
        root.geometry("1150x680")
        root.configure(bg=PUTIH)
        root.protocol("WM_DELETE_WINDOW", self.keluar)
        self.db = Database()
        self.keranjang, self.data_trx, self.role = {}, {}, None  # keranjang: kode -> qty
        self.atur_style()
        self.tampil_login()

    def keluar(self):
        self.db.conn.close()
        self.root.destroy()

    def atur_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Treeview", background=PUTIH, fieldbackground=PUTIH, rowheight=26,
                    font=("Segoe UI", 10))
        s.configure("Treeview.Heading", background=MERAH, foreground=PUTIH,
                    font=("Segoe UI", 10, "bold"))
        s.map("Treeview.Heading", background=[("active", MERAH_TUA)])
        s.map("Treeview", background=[("selected", "#FFCDD2")], foreground=[("selected", "black")])
        s.configure("TNotebook.Tab", padding=(20, 8), font=("Segoe UI", 10, "bold"))
        s.map("TNotebook.Tab", background=[("selected", MERAH)], foreground=[("selected", PUTIH)])

    def bersihkan(self):
        for w in self.root.winfo_children():
            w.destroy()

    def tombol(self, parent, teks, cmd, warna=MERAH):
        return tk.Button(parent, text=teks, command=cmd, bg=warna, fg=PUTIH,
                         activebackground=MERAH_TUA, activeforeground=PUTIH,
                         font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
                         cursor="hand2")

    def label(self, parent, teks, ukuran=10, tebal=False, fg="black", bg=PUTIH, rata=None, **pack):
        """Label yang langsung di-pack. rata = anchor teks; **pack = opsi pack."""
        kw = {"anchor": rata} if rata else {}
        lbl = tk.Label(parent, text=teks, bg=bg, fg=fg, **kw,
                       font=("Segoe UI", ukuran, "bold" if tebal else "normal"))
        lbl.pack(**pack)
        return lbl

    def entri(self, parent, var=None, ukuran=11, show="", **pack):
        e = tk.Entry(parent, textvariable=var, show=show, font=("Segoe UI", ukuran), bd=2,
                     relief="groove")
        e.pack(**pack)
        return e

    def bar_periode(self, parent, judul, aksi, tombol=None):
        """Baris atas: judul, (tombol opsional), pilihan periode. Mengembalikan combobox."""
        atas = tk.Frame(parent, bg=PUTIH)
        atas.pack(fill="x", padx=8, pady=8)
        self.label(atas, judul, 13, True, MERAH, side="left")
        if tombol:
            self.tombol(atas, *tombol).pack(side="right", padx=(5, 0))
        cb = ttk.Combobox(atas, values=PERIODE, state="readonly", width=16, font=("Segoe UI", 10))
        cb.current(0)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: aksi())
        self.label(atas, "Periode:", side="right", padx=5)
        return cb

    def tampil_login(self):
        self.bersihkan()
        self.keranjang = {}
        self.root.configure(bg=MERAH)
        box = tk.Frame(self.root, bg=PUTIH, padx=40, pady=30)
        box.place(relx=0.5, rely=0.5, anchor="center")
        self.label(box, "🛒 " + NAMA_TOKO.upper(), 18, True, MERAH, pady=(0, 5))
        self.label(box, "Silakan Login", 11, fg="gray", pady=(0, 20))
        self.label(box, "Username", rata="w", fill="x")
        self.ent_user = self.entri(box, fill="x", pady=(0, 10), ipady=4)
        self.label(box, "Password", rata="w", fill="x")
        self.ent_pass = self.entri(box, show="*", fill="x", pady=(0, 20), ipady=4)
        self.ent_user.bind("<Return>", lambda e: self.ent_pass.focus())
        self.ent_pass.bind("<Return>", lambda e: self.proses_login())
        self.ent_user.focus()
        self.tombol(box, "LOGIN", self.proses_login).pack(fill="x")

    def proses_login(self):
        peran = self.db.cek_login(self.ent_user.get().strip().lower(), self.ent_pass.get())
        if peran:
            self.role = peran
            self.tampil_utama()
        else:
            messagebox.showerror("Gagal", "Username atau password salah!")
            self.ent_pass.delete(0, "end")

    def tampil_utama(self):
        self.bersihkan()
        self.root.configure(bg=PUTIH)
        header = tk.Frame(self.root, bg=MERAH)
        header.pack(fill="x")
        self.label(header, "🛒 " + NAMA_TOKO, 16, True, PUTIH, MERAH, side="left", padx=15, pady=10)
        tk.Button(header, text="Logout", command=self.tampil_login, bg=PUTIH, fg=MERAH,
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=10).pack(side="right", padx=15)
        self.label(header, f"Login: {self.role}", fg=PUTIH, bg=MERAH, side="right")

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        tabs = [("  KASIR  ", self.buat_tab_kasir)]
        if self.role == "Admin":
            tabs += [("  KELOLA STOK & HARGA  ", self.buat_tab_admin),
                     ("  TRANSAKSI  ", self.buat_tab_transaksi),
                     ("  LAPORAN PENJUALAN  ", self.buat_tab_laporan)]
        for teks, pembuat in tabs:
            frame = tk.Frame(self.nb, bg=PUTIH)
            self.nb.add(frame, text=teks)
            pembuat(frame)
        if self.role == "Admin":  # refresh data tiap pindah tab (dipasang setelah semua tab ada)
            self.nb.bind("<<NotebookTabChanged>>", self.saat_tab_berubah)

    def saat_tab_berubah(self, _=None):
        self.isi_tabel_kasir()
        self.isi_tabel_admin()
        self.isi_tabel_transaksi()
        self.isi_laporan()

    def buat_tab_kasir(self, parent):
        kiri = tk.Frame(parent, bg=PUTIH)
        kiri.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        kanan = tk.Frame(parent, bg=ABU, width=430)
        kanan.pack(side="right", fill="y", padx=5, pady=5)
        kanan.pack_propagate(False)

        # -- Kiri: daftar produk --
        self.label(kiri, "Daftar Barang", 13, True, MERAH, anchor="w")
        frm_cari = tk.Frame(kiri, bg=PUTIH)
        frm_cari.pack(fill="x", pady=5)
        self.label(frm_cari, "Cari:", side="left")
        self.var_cari = tk.StringVar()
        self.var_cari.trace_add("write", lambda *a: self.isi_tabel_kasir())
        self.entri(frm_cari, self.var_cari, side="left", fill="x", expand=True, padx=5, ipady=3)

        self.tv_kasir = buat_tabel(kiri, [("kode", "Kode", 70), ("nama", "Nama Barang", 250),
                                          ("harga", "Harga Jual", 110), ("stok", "Stok", 60)])
        self.tv_kasir.pack(fill="both", expand=True)
        self.tv_kasir.bind("<Double-1>", lambda e: self.tambah_keranjang())
        self.tv_kasir.tag_configure("habis", foreground="red")

        frm_add = tk.Frame(kiri, bg=PUTIH)
        frm_add.pack(fill="x", pady=8)
        self.label(frm_add, "Jumlah:", side="left")
        self.spin_qty = tk.Spinbox(frm_add, from_=1, to=999, width=6, font=("Segoe UI", 11))
        self.spin_qty.pack(side="left", padx=5)
        self.tombol(frm_add, "+ Tambah ke Keranjang", self.tambah_keranjang).pack(side="left", padx=5)

        # -- Kanan: keranjang --
        self.label(kanan, "Keranjang Belanja", 13, True, MERAH, ABU, anchor="w", padx=8, pady=5)
        self.tv_cart = buat_tabel(kanan, [("nama", "Barang", 180), ("qty", "Qty", 45),
                                          ("sub", "Subtotal", 110)], height=10)
        self.tv_cart.pack(fill="x", padx=8)
        frm_btn = tk.Frame(kanan, bg=ABU)
        frm_btn.pack(fill="x", padx=8, pady=5)
        self.tombol(frm_btn, "Hapus Item", self.hapus_item, ABU_TOMBOL).pack(side="left", padx=(0, 5))
        self.tombol(frm_btn, "Kosongkan", self.kosongkan, ABU_TOMBOL).pack(side="left")

        self.lbl_total = self.label(kanan, "TOTAL: Rp 0", 18, True, MERAH, ABU, pady=(10, 5))
        self.label(kanan, "Uang Bayar (Rp):", bg=ABU, anchor="w", padx=8)
        self.var_bayar = tk.StringVar()
        self.var_bayar.trace_add("write", lambda *a: self.hitung_kembalian())
        ent = self.entri(kanan, self.var_bayar, 14, fill="x", padx=8, pady=3, ipady=4)
        ent.bind("<Return>", lambda e: self.bayar())
        self.lbl_kembali = self.label(kanan, "Kembalian: Rp 0", 14, True, HIJAU, ABU, pady=8)
        self.tombol(kanan, "BAYAR & CETAK STRUK", self.bayar).pack(fill="x", padx=8, pady=5)
        self.isi_tabel_kasir()

    def isi_tabel_kasir(self):
        self.tv_kasir.delete(*self.tv_kasir.get_children())
        for p in self.db.daftar_produk(self.var_cari.get().strip()):
            tag = ("habis",) if p["stok"] <= 0 else ()
            self.tv_kasir.insert("", "end", iid=p["kode"], tags=tag,
                                 values=(p["kode"], p["nama"], rp(p["harga_jual"]), p["stok"]))

    def tambah_keranjang(self):
        sel = self.tv_kasir.selection()
        if not sel:
            messagebox.showwarning("Info", "Pilih barang terlebih dahulu.")
            return
        try:
            qty = int(self.spin_qty.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Jumlah tidak valid.")
            return
        p = self.db.ambil_produk(sel[0])
        sudah = self.keranjang.get(sel[0], 0)
        if p is None or sudah + qty > p["stok"]:
            messagebox.showwarning("Stok Kurang", f"Stok {p['nama']} hanya {p['stok']}." if p
                                   else "Barang tidak ditemukan.")
            return
        self.keranjang[p["kode"]] = sudah + qty
        self.refresh_keranjang()

    def hapus_item(self):
        sel = self.tv_cart.selection()
        if sel:
            self.keranjang.pop(sel[0], None)
            self.refresh_keranjang()

    def kosongkan(self):
        self.keranjang.clear()
        self.refresh_keranjang()

    def total(self):
        produk = (self.db.ambil_produk(k) for k in self.keranjang)
        return sum(p["harga_jual"] * q for p, q in zip(produk, self.keranjang.values()) if p)

    def refresh_keranjang(self):
        self.tv_cart.delete(*self.tv_cart.get_children())
        for k, q in list(self.keranjang.items()):
            p = self.db.ambil_produk(k)
            if p is None:  # barang sudah dihapus dari database
                self.keranjang.pop(k)
                continue
            self.tv_cart.insert("", "end", iid=k, values=(p["nama"], q, rp(p["harga_jual"] * q)))
        self.lbl_total.config(text=f"TOTAL: {rp(self.total())}")
        self.hitung_kembalian()

    def ambil_bayar(self):
        teks = self.var_bayar.get().replace(".", "").replace(",", "").strip()
        return int(teks) if teks.isdigit() else 0

    def hitung_kembalian(self):
        kembali = self.ambil_bayar() - self.total()
        kurang = self.ambil_bayar() > 0 and kembali < 0
        self.lbl_kembali.config(text=f"Kurang: {rp(-kembali)}" if kurang else f"Kembalian: {rp(max(kembali, 0))}",
                                fg="red" if kurang else HIJAU)

    def bayar(self):
        if not self.keranjang:
            messagebox.showwarning("Info", "Keranjang masih kosong.")
            return
        bayar = self.ambil_bayar()
        if bayar < self.total():
            messagebox.showerror("Gagal", "Uang bayar kurang!")
            return
        sekarang = datetime.datetime.now()
        try:  # stok dikurangi + transaksi disimpan dalam satu transaksi database
            no, total, kembali, items = self.db.simpan_transaksi(
                self.role, self.keranjang, bayar, sekarang)
        except ValueError as e:
            messagebox.showerror("Gagal", str(e))
            self.refresh_keranjang()
            self.isi_tabel_kasir()
            return
        item_struk = [(i["nama"], i["qty"], i["harga_jual"]) for i in items]
        self.tampil_struk(self.buat_struk(item_struk, total, bayar, kembali, sekarang, no))
        self.keranjang.clear()
        self.var_bayar.set("")
        self.refresh_keranjang()
        self.isi_tabel_kasir()
        if self.role == "Admin":
            self.saat_tab_berubah()

    def buat_struk(self, items, total, bayar, kembali, waktu, no):
        lebar = 38
        baris = [NAMA_TOKO.upper().center(lebar), ALAMAT_TOKO.center(lebar), "=" * lebar,
                 f"No      : {no}", f"Tanggal : {waktu.strftime('%d-%m-%Y %H:%M:%S')}",
                 f"Kasir   : {self.role}", "-" * lebar]
        for nama, qty, harga in items:
            kiri = f"  {qty} x {rp(harga)}"
            baris += [nama[:lebar], kiri + rp(qty * harga).rjust(lebar - len(kiri))]
        baris.append("-" * lebar)
        for label, nilai in [("TOTAL", total), ("BAYAR", bayar), ("KEMBALI", kembali)]:
            baris.append(label + rp(nilai).rjust(lebar - len(label)))
        baris += ["=" * lebar, "Terima Kasih".center(lebar), "Selamat Belanja Kembali".center(lebar)]
        return "\n".join(baris)

    def tampil_struk(self, teks):
        os.makedirs(FOLDER_STRUK, exist_ok=True)
        nama_file = os.path.join(FOLDER_STRUK, "struk_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt")
        with open(nama_file, "w", encoding="utf-8") as f:
            f.write(teks)

        win = tk.Toplevel(self.root)
        win.title("Struk Pembayaran")
        win.configure(bg=PUTIH)
        win.geometry("400x540")
        txt = tk.Text(win, font=("Courier New", 10), width=40, bd=0)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", teks)
        txt.config(state="disabled")
        frm = tk.Frame(win, bg=PUTIH)
        frm.pack(pady=8)

        def cetak():
            try:
                os.startfile(os.path.abspath(nama_file), "print")  # Windows
            except Exception:
                messagebox.showinfo("Info", f"Struk tersimpan di:\n{os.path.abspath(nama_file)}\n"
                                            "Silakan cetak manual dari file tersebut.")

        self.tombol(frm, "🖨 Cetak", cetak).pack(side="left", padx=5)
        self.tombol(frm, "Tutup", win.destroy, ABU_TOMBOL).pack(side="left", padx=5)

    def buat_tab_admin(self, parent):
        form = tk.Frame(parent, bg=ABU, width=320)
        form.pack(side="right", fill="y", padx=5, pady=5)
        form.pack_propagate(False)
        kiri = tk.Frame(parent, bg=PUTIH)
        kiri.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        self.tv_admin = buat_tabel(kiri, [
            ("kode", "Kode", 60), ("nama", "Nama Barang", 200), ("beli", "Harga Beli", 100),
            ("jual", "Harga Jual", 100), ("laba", "Laba/Item", 90), ("stok", "Stok", 60)])
        self.tv_admin.pack(fill="both", expand=True)
        self.tv_admin.bind("<<TreeviewSelect>>", self.pilih_admin)
        self.tv_admin.bind("<Delete>", lambda e: self.hapus_admin())

        self.label(form, "Data Barang", 13, True, MERAH, ABU, pady=10)
        self.f_kode, self.f_nama, self.f_beli, self.f_jual, self.f_stok = (
            tk.StringVar() for _ in range(5))
        for teks, var in [("Kode (angka, kosongkan untuk otomatis)", self.f_kode),
                          ("Nama Barang", self.f_nama), ("Harga Beli (Rp)", self.f_beli),
                          ("Harga Jual (Rp)", self.f_jual), ("Stok", self.f_stok)]:
            self.label(form, teks, bg=ABU, rata="w", fill="x", padx=12)
            self.entri(form, var, fill="x", padx=12, pady=(0, 6), ipady=3)
        for teks, cmd, warna in [("Simpan (Tambah/Update)", self.simpan_admin, MERAH),
                                 ("Hapus Barang", self.hapus_admin, MERAH_TUA),
                                 ("Kosongkan Form", self.reset_form, ABU_TOMBOL)]:
            self.tombol(form, teks, cmd, warna).pack(fill="x", padx=12, pady=4)
        self.isi_tabel_admin()

    def isi_tabel_admin(self):
        self.tv_admin.delete(*self.tv_admin.get_children())
        for p in self.db.daftar_produk():
            self.tv_admin.insert("", "end", iid=p["kode"], values=(
                p["kode"], p["nama"], rp(p["harga_beli"]), rp(p["harga_jual"]),
                rp(p["harga_jual"] - p["harga_beli"]), p["stok"]))

    def pilih_admin(self, _=None):
        sel = self.tv_admin.selection()
        p = self.db.ambil_produk(sel[0]) if sel else None
        if p:
            for var, kunci in [(self.f_kode, "kode"), (self.f_nama, "nama"), (self.f_beli, "harga_beli"),
                               (self.f_jual, "harga_jual"), (self.f_stok, "stok")]:
                var.set(p[kunci])

    def reset_form(self):
        for v in (self.f_kode, self.f_nama, self.f_beli, self.f_jual, self.f_stok):
            v.set("")

    def segarkan_stok(self):  # Muat ulang semua tampilan yang menampilkan data produk.
        self.isi_tabel_admin()
        self.isi_tabel_kasir()
        self.refresh_keranjang()
        self.reset_form()

    def simpan_admin(self):
        kode, nama = self.f_kode.get().strip(), self.f_nama.get().strip()
        if kode and not kode.isdigit():
            messagebox.showerror("Error", "Kode barang harus berupa angka saja.")
            return
        try:
            beli, jual, stok = int(self.f_beli.get()), int(self.f_jual.get()), int(self.f_stok.get())
            if min(beli, jual, stok) < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Harga dan stok harus angka (>= 0).")
            return
        if not nama:
            messagebox.showerror("Error", "Nama barang wajib diisi.")
            return
        kode = kode or self.db.kode_berikutnya()
        if jual < beli and not messagebox.askyesno(
                "Peringatan", "Harga jual lebih kecil dari harga beli (rugi).\nTetap simpan?"):
            return
        self.db.simpan_produk(kode, nama, beli, jual, stok)
        self.segarkan_stok()
        messagebox.showinfo("Sukses", f"Data barang (kode {kode}) tersimpan.")

    def hapus_admin(self):
        sel = self.tv_admin.selection()
        if not sel:
            messagebox.showwarning("Info", "Pilih barang yang akan dihapus.")
            return
        p = self.db.ambil_produk(sel[0])
        if p and messagebox.askyesno(
                "Konfirmasi Hapus",
                f"Hapus barang berikut?\n\nKode : {p['kode']}\nNama : {p['nama']}\n"
                f"Stok : {p['stok']}\n\nRiwayat transaksi lama tidak ikut terhapus."):
            self.db.hapus_produk(p["kode"])
            self.keranjang.pop(p["kode"], None)
            self.segarkan_stok()
            messagebox.showinfo("Sukses", f"Barang '{p['nama']}' berhasil dihapus.")

    def buat_tab_transaksi(self, parent):
        self.cb_trx = self.bar_periode(parent, "Riwayat Transaksi", self.isi_tabel_transaksi,
                                       ("Refresh", self.isi_tabel_transaksi, ABU_TOMBOL))
        self.tv_trx = buat_tabel(parent, [
            ("no", "No", 50), ("waktu", "Waktu", 160), ("kasir", "Kasir", 90),
            ("item", "Jml Barang", 90), ("total", "Total", 130), ("laba", "Laba", 120)], height=10)
        self.tv_trx.pack(fill="both", expand=True, padx=8)
        self.tv_trx.bind("<<TreeviewSelect>>", self.tampil_detail_transaksi)
        self.lbl_trx_info = self.label(parent, "", fg="gray", anchor="w", padx=8, pady=(4, 0))

        self.label(parent, "Rincian Transaksi Terpilih", 11, True, MERAH, anchor="w", padx=8, pady=(8, 2))
        self.tv_detail = buat_tabel(parent, [
            ("nama", "Barang", 280), ("qty", "Qty", 60), ("harga", "Harga Satuan", 130),
            ("sub", "Subtotal", 130)], height=5)
        self.tv_detail.pack(fill="x", padx=8)
        self.lbl_detail_bayar = self.label(parent, "", 10, True, anchor="w", padx=8, pady=(4, 8))
        self.isi_tabel_transaksi()

    def isi_tabel_transaksi(self):
        self.tv_trx.delete(*self.tv_trx.get_children())
        self.tv_detail.delete(*self.tv_detail.get_children())
        self.lbl_detail_bayar.config(text="")
        data = self.db.daftar_transaksi(self.cb_trx.get())  # terbaru di atas
        self.data_trx = {t["no"]: t for t in data}
        for t in data:
            waktu = datetime.datetime.strptime(t["waktu"], FMT_WAKTU).strftime("%d-%m-%Y %H:%M")
            self.tv_trx.insert("", "end", iid=str(t["no"]), values=(
                t["no"], waktu, t["kasir"], t["jml"], rp(t["total"]), rp(t["laba"])))
        total = sum(t["total"] for t in data)
        self.lbl_trx_info.config(text=f"{len(data)} transaksi  |  Total penjualan: {rp(total)}")

    def tampil_detail_transaksi(self, _=None):
        sel = self.tv_trx.selection()
        self.tv_detail.delete(*self.tv_detail.get_children())
        t = self.data_trx.get(int(sel[0])) if sel else None
        if not t:
            return
        for i in self.db.item_transaksi(t["no"]):
            self.tv_detail.insert("", "end", values=(
                i["nama"], i["qty"], rp(i["harga_jual"]), rp(i["harga_jual"] * i["qty"])))
        self.lbl_detail_bayar.config(
            text=f"Total: {rp(t['total'])}   |   Bayar: {rp(t['bayar'])}   |   Kembali: {rp(t['kembali'])}")

    def buat_tab_laporan(self, parent):
        self.cb_lap = self.bar_periode(parent, "Laporan Penjualan", self.isi_laporan,
                                       ("Simpan Laporan (.txt)", self.simpan_laporan))
        kartu_frame = tk.Frame(parent, bg=PUTIH)
        kartu_frame.pack(fill="x", padx=8, pady=5)
        self.kartu = {}
        for kunci, judul in [("trx", "Jumlah Transaksi"), ("qty", "Barang Terjual"),
                             ("pendapatan", "Pendapatan"), ("modal", "Modal (HPP)"),
                             ("laba", "Laba Bersih")]:
            k = tk.Frame(kartu_frame, bg=MERAH, padx=10, pady=8)
            k.pack(side="left", fill="x", expand=True, padx=4)
            self.label(k, judul, 9, fg=PUTIH, bg=MERAH)
            self.kartu[kunci] = self.label(k, "0", 15, True, PUTIH, MERAH)

        self.label(parent, "Penjualan per Produk", 11, True, MERAH, anchor="w", padx=8, pady=(10, 2))
        self.tv_lap = buat_tabel(parent, [
            ("kode", "Kode", 60), ("nama", "Nama Barang", 280), ("qty", "Terjual", 80),
            ("pendapatan", "Pendapatan", 150), ("laba", "Laba", 150)])
        self.tv_lap.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.isi_laporan()

    def isi_laporan(self):
        lap = self.db.laporan(self.cb_lap.get())
        nilai = {"trx": str(lap["jumlah"]), "qty": str(lap["qty"]), "pendapatan": rp(lap["pendapatan"]),
                 "modal": rp(lap["modal"]), "laba": rp(lap["pendapatan"] - lap["modal"])}
        for kunci, teks in nilai.items():
            self.kartu[kunci].config(text=teks)
        self.tv_lap.delete(*self.tv_lap.get_children())
        for d in lap["per_produk"]:
            self.tv_lap.insert("", "end", values=(
                d["kode"], d["nama"], d["qty"], rp(d["pendapatan"]), rp(d["laba"])))

    def simpan_laporan(self):
        periode = self.cb_lap.get()
        lap = self.db.laporan(periode)
        lebar = 60
        baris = [NAMA_TOKO.upper().center(lebar), "LAPORAN PENJUALAN".center(lebar),
                 f"Periode : {periode}",
                 f"Dicetak : {datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')}", "=" * lebar,
                 f"Jumlah Transaksi : {lap['jumlah']}", f"Barang Terjual   : {lap['qty']}",
                 f"Pendapatan       : {rp(lap['pendapatan'])}", f"Modal (HPP)      : {rp(lap['modal'])}",
                 f"Laba Bersih      : {rp(lap['pendapatan'] - lap['modal'])}", "=" * lebar,
                 "PENJUALAN PER PRODUK", "-" * lebar]
        for d in lap["per_produk"]:
            baris += [f"[{d['kode']}] {d['nama']}",
                      f"    Terjual {d['qty']}  |  Pendapatan {rp(d['pendapatan'])}  |  Laba {rp(d['laba'])}"]
        if not lap["per_produk"]:
            baris.append("(belum ada penjualan pada periode ini)")
        os.makedirs(FOLDER_LAPORAN, exist_ok=True)
        nama_file = os.path.join(FOLDER_LAPORAN, "laporan_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt")
        with open(nama_file, "w", encoding="utf-8") as f:
            f.write("\n".join(baris))
        messagebox.showinfo("Tersimpan", f"Laporan tersimpan di:\n{os.path.abspath(nama_file)}")


if __name__ == "__main__":
    root = tk.Tk()
    Aplikasi(root)
    root.mainloop()
