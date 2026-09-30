# Hongguo Drama VIP Downloader (红果短剧) 🎬 v1.0.2

កម្មវិធី Desktop ទំនើប និងស្រស់ស្អាត (Modern PyQt6 Cinema UI) សម្រាប់រុករក មើលតារាងរឿងល្បីៗ រក្សាទុក្ខរឿងដែលចូលចិត្ត ទស្សនារឿងផ្ទាល់ក្នុងកម្មវិធី និងដោនឡូតវីដេអូរឿងពេញកម្រិត 1080p Full HD MP4 គ្រប់ភាគដោយឥតគិតថ្លៃ (VIP Unlimited)។

---

## 📌 កំណត់ចំណាំសំខាន់ៗ (Important Notes)

### ១. សម្រាប់អ្នកប្រើប្រាស់ទូទៅ (End-User Instructions)
* **ឯកសារដំឡើង (Installer)**៖ ប្រើប្រាស់ឯកសារ `HongguoDownloader-Setup.exe` ឬពន្លា `HongguoDownloader-Setup.zip` រួចចុចដំឡើងជាការស្រេច។
* **គ្មានតម្រូវការបន្ថែម (Zero Dependency)**៖ មិនបាច់ដំឡើង Python, Java ឬកម្មវិធីជំនួយអ្វីទាំងអស់ ព្រោះបានបង្កប់មកជាមួយរួចរាល់ 100%។
* **Windows SmartScreen / Antivirus Note**៖ ដោយសារជាកម្មវិធីទើបតែ Build ថ្មី ប្រសិនបើ Windows បង្ហាញផ្ទាំងការពារ សូមចុចលើ **"More info"** រួចជ្រើសរើស **"Run anyway"**។
* **Engine Background Service**៖ នៅពេលបើកកម្មវិធី Engine (Python Port 8000 & Java Signer 9099) នឹងចាប់ផ្តើមដោយស្វ័យប្រវត្តិកំបាំងនៅ background ភ្លាមៗ (ឃើញសញ្ញា `🟢 Engine Ready`)។

---

## ✨ មុខងារចម្បង និងចំណុចថ្មីក្នុងជំនាន់ v1.0.2 (Changelog & Features)

### 1. 🏆 English Cinema UI Redesign
- កែប្រែ UI ទៅជាភាសាអង់គ្លេសស្អាត ទំនើប និងបែប Cinema Dark Theme (Purple & Amber Neon)。
- Poster រឿងកម្រិតច្បាស់សមាមាត្រ 1:1.37 Cinema Portrait។

### 2. 📺 In-App Single-Window Drama Hub (លែងមាន Popups ច្រើនជាន់)
- ប្តូរមកប្រើផ្ទាំង Hub តែមួយក្នុង Main Window (មានប៊ូតុង `[ ← Back ]` ត្រឡប់ក្រោយដោយមិនបាត់ទិន្នន័យ)។
- ផ្ទុក Hero Banner រួមមាន៖ ឈ្មោះរឿង, Poster HD, Series ID, Badges, និងប្រអប់កត់ត្រា **Personal Notes**។

### 3. 🎯 Interactive Visual Episode Selection Grid
- **ស្វែងរកចំនួន Episode ពិតប្រាកដស្វ័យប្រវត្តិ (លែងឃើញ 0 Eps)** តាមរយៈ Engine API។
- បន្ទះក្រឡាជ្រើសរើសភាគ **16 Columns** ពណ៌ Glowing Orange Gradient ងាយស្រួលមើល។
- **Single-click**៖ ជ្រើសរើសភាគសម្រាប់ដោនឡូត (ប៊ូតុងខាងក្រោម update ចំនួនភ្លាមៗ)។
- **Double-click**៖ បើកចាក់មើលវីដេអូនោះភ្លាមៗក្នុង Cinema Player។
- **Range Tabs**៖ `All (1-N)`, `1 - 30`, `31 - 60`, `61 - 90`...
- **Batch Tools**៖ `✓ Select All`, `✕ Clear`, `⚡ Ep 1-5 (Test)` សម្រាប់ download តេស្តមើល 5 ភាគដំបូង។

### 4. ⚡ Lossless 1080p Downloader & Command Deck
- ជ្រើសរើសគុណភាពវីដេអូ (`1080p Best - Full HD`, `720p HD`, `480p SD`)។
- ជ្រើសរើសថតរក្សាទុក (Save Folder)។
- ប៊ូតុងបញ្ជាដោនឡូតឌីណាមិក `[ ⬇ Start Download (N Episodes) ]`។

### 5. 📝 Personal Notes & Saved Library
- កត់ត្រាចំណាំផ្ទាល់ខ្លួន (Notes) លើរឿងនីមួយៗ និងរក្សាទុកក្នុង SQLite Database ក្នុងម៉ាស៊ីន (Offline Persistent)។

---

## 🛠️ របៀប Build ឯកសារដំឡើង (Developer Build)

```bash
# ១. បើកដំណើរការកម្មវិធីតេស្ត
python main.py

# ២. Build ចេញជា Setup Installer សម្រាប់ចែកចាយ
python build_installer.py
```
