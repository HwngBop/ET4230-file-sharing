# Hướng dẫn chạy Client — Sprint 1

Client dòng lệnh kết nối tới Server qua TCP, hỗ trợ upload, download, list và ngắt kết nối. Client tuân thủ protocol mô tả trong `report/protocol.md` và dùng lại lớp `Connection` trong `src/common/protocol.py`.

## 1. Yêu cầu

- Python 3.11.x
- Đã cài thư viện theo `requirements.txt`
- Một Server đang chạy và máy client truy cập được địa chỉ IP, port của server (cách chạy server xem `report/server-guide.md`)

Client chỉ dùng thư viện chuẩn của Python, không cần cài thêm gói nào cho riêng client.

## 2. Cài đặt môi trường

Chạy các lệnh sau tại thư mục gốc của project (Windows PowerShell):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Nếu repo đã có `pyproject.toml`, chạy thêm lệnh sau (giống `report/server-guide.md`) để Python tìm thấy các package trong `src/`:

```powershell
pip install -e . --no-deps
```

Client không cần bước này vì chạy bằng `python -m src.client.client`. Chỉ lệnh chạy server `python -m server` cần nó, hoặc dùng cách thay thế ở mục 6.

Trên Linux/macOS dùng `python3.11 -m venv .venv` và `source .venv/bin/activate`.

## 3. Chạy Client

Tại thư mục gốc project, với venv đã kích hoạt:

```powershell
python -m src.client.client
```

Client hiện dấu nhắc `>` và chờ lệnh. Lần chạy đầu tiên client tự tạo hai thư mục:

| Thư mục | Công dụng |
| --- | --- |
| `client_data/uploads/` | Đặt file cần upload lên server |
| `client_data/downloads/` | Nơi lưu file tải về từ server |

## 4. Các lệnh

| Lệnh | Ý nghĩa |
| --- | --- |
| `connect <ip> [port]` | Kết nối tới server. Port mặc định là 5000 |
| `upload <file>` | Upload file lên server |
| `download <filename>` | Tải file từ server về `client_data/downloads/` |
| `list` | Liệt kê file đang có trên server |
| `quit` | Ngắt kết nối đúng cách và thoát client |
| `help` | Hiển thị danh sách lệnh |

Tên lệnh không phân biệt hoa/thường ở phía client (ví dụ `LIST` và `list` đều được). Không hard-code `localhost`: địa chỉ server luôn do người dùng nhập ở lệnh `connect`.

Về đường dẫn file khi upload:

- Có thể gõ đường dẫn đầy đủ hoặc tương đối, ví dụ `upload C:\Users\me\report.pdf`.
- Nếu chỉ gõ tên file, client tìm trong thư mục hiện tại, sau đó trong `client_data/uploads/`.
- Đường dẫn có khoảng trắng nên đặt trong dấu ngoặc kép, ví dụ `upload "my report.pdf"`.

Lệnh `download` chỉ nhận tên file đơn, không nhận đường dẫn.

## 5. Ví dụ một phiên làm việc

```text
> connect 192.168.1.10 5000
Connected to server.
> list
Server has no files.
> upload test.pdf
Uploading test.pdf
Size: 10.0 MB
Transfer completed.
Time: 0.85 s, Speed: 11.76 MB/s
> list
Files on server (1):
  test.pdf
> download test.pdf
Downloading test.pdf
Size: 10.0 MB
Transfer completed.
Saved to: ...\client_data\downloads\test.pdf
Time: 0.60 s, Speed: 16.67 MB/s
> quit
Disconnected from server.
```

(Con số kích thước, thời gian, tốc độ ở trên chỉ là ví dụ.)

## 6. Kiểm tra trên một máy

1. Terminal 1: kích hoạt venv, chạy server tại thư mục gốc project rồi chờ dòng log `LISTENING`:

   ```powershell
   python -m server --host 0.0.0.0 --port 5000
   ```

   Nếu báo `No module named server` (chưa cài editable), chạy thêm dòng sau trước lệnh trên, hoặc dùng `set PYTHONPATH=src` nếu bạn dùng CMD:

   ```powershell
   $env:PYTHONPATH="src"
   ```

   Các tham số khác (`--config`, `--storage-dir`, `--client-timeout`...) xem `report/server-guide.md`. Dừng server bằng `Ctrl+C`.
2. Terminal 2 (cũng kích hoạt venv): chạy client, gõ `connect 127.0.0.1 5000`, rồi thử `list`, `upload`, `download`, `quit`.

`127.0.0.1` chỉ dùng để thử nhanh khi server và client cùng một máy.

## 7. Kiểm tra giữa hai máy

1. Trên máy server: chạy `ipconfig` và lấy địa chỉ IPv4 của card mạng đang dùng.
2. Đảm bảo hai máy cùng mạng LAN/Wi-Fi.
3. Nếu cần, cho phép Python/TCP port 5000 (hoặc port đã cấu hình trong `configs/server.json`) qua Windows Firewall trên máy server.
4. Trên máy client: `connect <IPv4 của server> 5000`, sau đó chạy đủ `list`, `upload`, `download`, `quit`.

Phải dùng IPv4 thực của máy server. Không dùng `0.0.0.0`: đó chỉ là địa chỉ server lắng nghe, không phải địa chỉ để kết nối tới.

## 8. Thông báo lỗi thường gặp

Client không bị thoát khi gặp các lỗi dưới đây, người dùng có thể nhập lệnh tiếp.

| Thông báo | Nguyên nhân và cách xử lý |
| --- | --- |
| `Not connected. Use: connect <ip> [port]` | Chưa kết nối. Chạy `connect` trước |
| `Already connected. Use 'quit' to disconnect first.` | Đang có kết nối. Dùng `quit` rồi chạy lại client để kết nối server khác |
| `Server not reachable: ... refused the connection` | Server chưa chạy hoặc sai port |
| `Server not reachable: ... timed out` | Sai IP, khác mạng, hoặc firewall chặn |
| `Invalid or unknown server address` | Địa chỉ nhập không hợp lệ |
| `Local file does not exist: <file>` | File upload không có ở đường dẫn đã nhập hay trong `client_data/uploads/` |
| `Invalid command: <lệnh>` | Gõ sai tên lệnh. Dùng `help` để xem danh sách |
| `Server error FILE_NOT_FOUND: ...` | File cần download không có trên server. Dùng `list` để kiểm tra tên |
| `Server error INVALID_FILENAME: ...` | Tên file bị server từ chối (ký tự không hợp lệ, tên quá dài, tên đặc biệt của Windows) |
| `Server error FILE_TOO_LARGE: ...` | File vượt `max_file_size` của server (mặc định 1 GB) |
| `Server did not respond in time. Connection closed.` | Server không phản hồi trong 30 giây. Kết nối lại bằng `connect` |
| `Server closed the connection. Connection closed.` | Server đóng kết nối giữa chừng. Kết nối lại |

Khi server báo các lỗi nghiêm trọng (`TIMEOUT`, `TRANSFER_INCOMPLETE`, `CONNECTION_OR_IO_ERROR`, `INVALID_HEADER`, `HEADER_TOO_LARGE`), protocol quy định server đóng kết nối. Client tự đóng socket và cần `connect` lại.

## 9. Hành vi cần biết

- Upload ghi đè file trùng tên trên server.
- Download ghi đè file trùng tên trong `client_data/downloads/`. Dữ liệu được ghi vào file `.part` rồi mới đổi tên khi tải xong, nên tải hỏng không để lại file dở.
- Server hiện xử lý một client tại một thời điểm. Client thứ hai phải chờ client đầu `quit`, đóng kết nối hoặc hết timeout (mặc định 30 giây).
- File upload được server lưu trong `src/server/storage/` (mặc định, theo `configs/server.json`).
- Mỗi lần chuyển file client in thêm thời gian và tốc độ để tham khảo, chưa phải số liệu benchmark chính thức.

## 10. Giới hạn của Sprint 1

- Chưa có kiểm tra checksum: client chỉ kiểm tra đủ số byte theo `file_size`.
- Chưa có TLS: dữ liệu truyền qua mạng **không được mã hóa**. Không dùng để truyền dữ liệu nhạy cảm.
- Chưa có resume, tự động thử lại, progress bar nâng cao, đăng nhập, GUI và nhiều transfer đồng thời.
