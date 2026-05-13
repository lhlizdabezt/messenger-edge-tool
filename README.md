# Messenger Edge Tool

Tool nho chay local de mo Messenger bang Microsoft Edge, dien tin nhan vao o chat, va chi gui khi ban bam nut xac nhan.

Tool co them tab `AI viet nhap` de soan ban nhap tin nhan. Ban duyet noi dung truoc, sau do moi dien hoac gui.

## Cai dat

Mo PowerShell trong thu muc nay, roi chay:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

## Chay tool

Mo file `run.bat`.

Lan dau Edge mo ra, ban dang nhap Messenger trong cua so do. Phien dang nhap duoc luu trong thu muc `edge_profile` ngay canh tool, khong luu mat khau trong code.

## Cach dung

1. Vao tab `Soan tin`.
2. Nhap link Messenger, username hoac id vao o `Link / username / id`.
3. Nhap noi dung tin nhan, hoac qua tab `AI viet nhap` de tao ban nhap.
4. Bam `Dien tin nhan` neu chi muon dien vao o chat.
5. Bam `Gui co xac nhan` neu muon tool dien va bam Enter de gui.

Ban co the luu lien he bang `Ten goi nho` + `Luu lien he`. Danh sach nay duoc luu trong `contacts.json`.

## Dung AI

Ban can API key OpenAI-compatible. Voi Woku Shop, dung:

1. `API key`: key Woku bat dau bang `sk-...`
2. `Base URL`: `https://llm.wokushop.com/v1`
3. `Model`: `gpt-4o-mini`

Ban cung co the dat bien moi truong Windows:

```powershell
setx OPENAI_API_KEY "sk-..."
setx OPENAI_BASE_URL "https://llm.wokushop.com/v1"
setx OPENAI_MODEL "gpt-4o-mini"
```

Sau do mo lai `run.bat`.

Neu dung OpenAI that, doi `Base URL` thanh `https://api.openai.com/v1` va dung key OpenAI hop le.

Trong tab AI, nhap `Boi canh` neu can, nhap dieu muon noi vao `Y muon noi`, chon giong van, roi bam `AI soan nhap`.

Ban cung co the de tool doc ngu canh tu Messenger:

1. Mo dung cuoc tro chuyen trong tab `Soan tin`.
2. Qua tab `AI viet nhap`.
3. Bam `Doc chat` de dua cac dong chat dang hien thi vao o `Boi canh`.
4. Bam `Doc chat + dien tra loi` de tool doc chat, goi AI, roi dien cau tra loi vao o chat Messenger.
5. Bam `Bat auto khi co tin moi` neu muon tool ghi nho doan chat hien tai, moi tin moi cua doi phuong chi tu dien 1 lan, roi tiep tuc cho tin ke tiep.
6. Neu chi dung demo voi chat test, tick `Demo auto gui` truoc khi bam auto. Khi do tool se tu bam Enter gui sau khi AI soan, moi tin moi cua doi phuong chi gui 1 lan.

Mac dinh tool khong tu bam Enter. Che do `Demo auto gui` can duoc tick rieng. Auto se tiep tuc chay den khi ban bam tat auto hoac dong tool.

## Luu y

- Khong dung tool de spam, quay roi, hoac gui tin nhan cho nguoi khong muon nhan.
- AI chi nen dung de soan nhap. Ban van la nguoi xac nhan truoc khi gui.
- Neu tool khong tim thay o chat, hay mo dung cuoc tro chuyen roi bam lai.
- Neu Edge khong mo duoc, hay kiem tra ban da cai Microsoft Edge ban desktop.
