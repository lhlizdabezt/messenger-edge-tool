# Messenger Edge Tool

Công cụ chạy cục bộ để mở Messenger bằng Microsoft Edge, điền nội dung tin nhắn vào ô chat và chỉ gửi khi bạn xác nhận.

Công cụ có thêm tab `AI viết nháp` để tạo bản nháp tin nhắn. Bạn có thể đọc, chỉnh lại nội dung rồi mới điền hoặc gửi.

## Cài đặt

Mở PowerShell trong thư mục này, sau đó chạy:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Lệnh trên sẽ tạo môi trường Python cục bộ và cài các thư viện cần thiết.

## Chạy công cụ

Mở file:

```powershell
.\run.bat
```

Lần đầu Edge mở lên, hãy đăng nhập Messenger trong cửa sổ đó. Phiên đăng nhập được lưu trong thư mục `edge_profile` nằm cạnh tool, không lưu mật khẩu trong mã nguồn.

## Cách dùng

1. Vào tab `Soạn tin`.
2. Nhập link Messenger, username hoặc ID vào ô `Link / username / id`.
3. Nhập nội dung tin nhắn, hoặc chuyển sang tab `AI viết nháp` để tạo bản nháp.
4. Bấm `Điền tin nhắn` nếu chỉ muốn điền nội dung vào ô chat.
5. Bấm `Gửi có xác nhận` nếu muốn tool điền nội dung và gửi sau khi bạn xác nhận.

Bạn có thể lưu liên hệ bằng `Tên gợi nhớ` + `Lưu liên hệ`. Danh sách liên hệ được lưu trong file `contacts.json`.

## Dùng AI

Bạn cần một API key tương thích OpenAI. Nếu dùng Woku Shop, cấu hình như sau:

1. `API key`: key Woku bắt đầu bằng `sk-...`
2. `Base URL`: `https://llm.wokushop.com/v1`
3. `Model`: `gpt-4o-mini`

Bạn cũng có thể đặt biến môi trường trên Windows:

```powershell
setx OPENAI_API_KEY "sk-..."
setx OPENAI_BASE_URL "https://llm.wokushop.com/v1"
setx OPENAI_MODEL "gpt-4o-mini"
```

Sau khi đặt biến môi trường, hãy mở lại `run.bat`.

Nếu dùng OpenAI chính thức, đổi `Base URL` thành `https://api.openai.com/v1` và dùng API key OpenAI hợp lệ.

Trong tab AI, nhập `Bối cảnh` nếu cần, nhập điều muốn nói vào `Ý muốn nói`, chọn giọng văn rồi bấm `AI soạn nháp`.

Bạn cũng có thể để tool đọc ngữ cảnh từ Messenger:

1. Mở đúng cuộc trò chuyện trong tab `Soạn tin`.
2. Chuyển sang tab `AI viết nháp`.
3. Bấm `Đọc chat` để đưa các dòng chat đang hiển thị vào ô `Bối cảnh`.
4. Bấm `Đọc chat + điền trả lời` để tool đọc chat, gọi AI và điền câu trả lời vào ô chat Messenger.
5. Bấm `Bật auto khi có tin mới` nếu muốn tool ghi nhớ đoạn chat hiện tại. Mỗi tin mới từ đối phương chỉ được xử lý một lần, sau đó tool tiếp tục chờ tin tiếp theo.
6. Nếu chỉ dùng demo với chat test, tick `Demo auto gửi` trước khi bật auto. Khi đó tool sẽ tự bấm Enter để gửi sau khi AI soạn xong.

Mặc định tool không tự bấm Enter. Chế độ `Demo auto gửi` phải được bật riêng. Auto sẽ tiếp tục chạy cho đến khi bạn tắt auto hoặc đóng tool.

## Lưu ý

- Không dùng tool để spam, quấy rối hoặc gửi tin nhắn cho người không muốn nhận.
- AI chỉ nên dùng để soạn nháp. Bạn vẫn là người kiểm tra và xác nhận nội dung trước khi gửi.
- Nếu tool không tìm thấy ô chat, hãy mở đúng cuộc trò chuyện rồi thử lại.
- Nếu Edge không mở được, hãy kiểm tra Microsoft Edge bản desktop đã được cài trên máy.
- Các thư mục/file như `.venv`, `edge_profile`, `contacts.json` và `.env` đã được đưa vào `.gitignore` để tránh đẩy dữ liệu cá nhân hoặc thông tin đăng nhập lên GitHub.
