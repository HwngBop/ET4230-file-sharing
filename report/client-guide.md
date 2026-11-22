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
Size: 10.0 MiB
Transfer completed; SHA-256 MATCH.
Time: 0.850 s, Application throughput: 98.68 Mbps
> list
Files on server (1):
  test.pdf
> download test.pdf
Downloading test.pdf
Size: 10.0 MiB
Transfer completed; SHA-256 MATCH.
Time: 0.600 s, Application throughput: 139.81 Mbps
> quit
Disconnected from server.
```

(Con số kích thước, thời gian, tốc độ ở trên chỉ là ví dụ. File tải về nằm trong `client_data/downloads/`.)

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
| `Server error FILE_BUSY: ...` | File đang được một lượt truyền khác sử dụng. **Phiên vẫn mở**, chờ một lúc rồi thử lại. Client không gửi dữ liệu file |
| `Server error SERVER_BUSY: ...` | Server quá tải. Client đóng kết nối, chờ một lúc rồi chạy lại `connect` |
| `Server error CHECKSUM_MISMATCH: ...` | Dữ liệu upload bị sai khi tới server. Server giữ nguyên file cũ, phiên vẫn mở, thử upload lại |
| `CHECKSUM_MISMATCH: received file bytes differ...` | File tải về sai checksum. Client xóa file tạm, **không ghi đè** file cũ, đóng kết nối. Dùng `connect` rồi thử lại |
| `Cannot read local file ...` | File local đang bị chương trình khác khóa hoặc không đọc được. Client chưa gửi gì lên server, phiên vẫn mở. Đóng chương trình đang dùng file rồi thử lại |
| `Connection lost during upload/download after X of Y bytes` | Mất kết nối giữa lúc truyền. Lượt truyền bị đánh dấu `FAILED`, file tải dở bị xóa. Dùng `connect` để tạo phiên mới và truyền lại từ đầu |
| `... the result is unverified` | Mất kết nối sau khi gửi hết dữ liệu nhưng trước khi server xác nhận. Không biết server đã lưu hay chưa: dùng `connect`, `list` để kiểm tra rồi upload lại nếu cần |
| `Server did not respond in time. Connection closed.` | Server không phản hồi trong 30 giây. Kết nối lại bằng `connect` |
| `Server closed the connection. Connection closed.` | Server đóng kết nối giữa chừng. Kết nối lại |

Client phân loại lỗi của server thành hai nhóm:

| Nhóm | Mã lỗi | Hành vi của client |
| --- | --- | --- |
| Recoverable | `INVALID_COMMAND`, `INVALID_FILENAME`, `INVALID_FILE_SIZE`, `FILE_TOO_LARGE`, `INVALID_CHECKSUM`, `CHECKSUM_MISMATCH`, `FILE_NOT_FOUND`, `FILE_BUSY` | Báo lỗi, giữ kết nối, có thể gõ lệnh tiếp |
| Fatal | `SERVER_BUSY`, `TIMEOUT`, `TRANSFER_INCOMPLETE`, `CONNECTION_OR_IO_ERROR`, `INVALID_HEADER`, `HEADER_TOO_LARGE` và mọi mã lạ chưa biết | Báo lỗi, tự đóng socket, cần chạy lại `connect` |

Khi không chắc server còn giữ kết nối hay không, client chọn đóng socket cho an toàn.

## 9. Hành vi cần biết

- Upload ghi đè file trùng tên trên server.
- Download ghi đè file trùng tên trong `client_data/downloads/`. Dữ liệu được ghi vào file `.part` rồi mới đổi tên khi tải xong, nên tải hỏng không để lại file dở.
- Server hiện xử lý một client tại một thời điểm. Client thứ hai phải chờ client đầu `quit`, đóng kết nối hoặc hết timeout (mặc định 30 giây).
- File upload được server lưu trong `src/server/storage/` (mặc định, theo `configs/server.json`).
- Client chỉ in `SHA-256 MATCH` khi server đã xác nhận checksum khớp. Thiếu hoặc sai checksum thì lượt truyền bị coi là thất bại.
- File tải về chỉ xuất hiện trong `client_data/downloads/` sau khi nhận đủ byte và checksum đúng. Nếu lỗi, file tạm `.part` bị xóa và file cũ (nếu có) được giữ nguyên.
- Client không tự động thử lại. Khi lỗi giữa chừng, người dùng tự chạy `connect` và gõ lại lệnh.

## 10. Ghi kết quả CSV

Mỗi lần upload/download đều ghi một dòng vào file CSV (mặc định `results/raw/baseline.csv`):

- Thành công: `status = SUCCESS`, `checksum_match = true`, có `throughput_mbps`.
- Thất bại: `status = FAILED`, `error_message` ghi nguyên nhân, `throughput_mbps` để trống. Lượt truyền chưa được server xác nhận checksum không bao giờ có throughput hợp lệ.

## 11. Chạy nhiều client cùng lúc để test

Mỗi client là **một tiến trình riêng** (mỗi cửa sổ terminal một lần chạy). Không dùng một `FileClient` từ nhiều thread cùng lúc: nếu làm vậy client báo `RuntimeError` (có thể chuyển giao client cho thread khác, miễn là không dùng đồng thời). Hãy cho mỗi instance thư mục tải và file CSV riêng để các lần chạy không đè lên nhau:

```powershell
python -m src.client.client --download-dir client_data/downloads_1 --csv results/raw/client1.csv
python -m src.client.client --download-dir client_data/downloads_2 --csv results/raw/client2.csv
```

File CSV không được thiết kế cho nhiều tiến trình ghi cùng lúc, nên đừng dùng chung một file `--csv`.

## 12. Giới hạn hiện tại

- Chưa có TLS: dữ liệu truyền qua mạng **không được mã hóa**. Không dùng để truyền dữ liệu nhạy cảm.
- Chưa có resume, tự động thử lại, progress bar nâng cao, đăng nhập, GUI và nhiều transfer đồng thời.
