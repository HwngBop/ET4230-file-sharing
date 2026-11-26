# Hướng dẫn chạy Client — Sprint 2

Client dòng lệnh kết nối tới Server qua TCP, hỗ trợ upload, download, list và ngắt kết nối. Client tuân thủ protocol mô tả trong `report/protocol.md` và dùng lại lớp `Connection` trong `src/common/protocol.py`.

Từ Sprint 2, Client xử lý rõ các lỗi khi nhiều client dùng chung một Server (Server đầy, file đang bận, mất kết nối, truyền dở) theo hợp đồng lỗi S2-01 v1.0. Giao diện lệnh và giao thức JSON+LF giữ nguyên như Sprint 1.

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

**Lưu ý về `connect`:** dòng `Connected to server.` chỉ có nghĩa là kết nối TCP đã được thiết lập. Server không gửi lời chào và Client cũng không chờ lời chào. Nếu Server đã đủ số kết nối tối đa (`max_clients`, mặc định 10), Server từ chối ngay sau khi chấp nhận kết nối, nên lỗi `SERVER_BUSY` chỉ hiện ra ở **lệnh đầu tiên** sau `connect` (ví dụ `list`). Khi đó chờ một lúc rồi gõ lại `connect`.

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

Client không bị thoát khi gặp các lỗi dưới đây. Với lỗi recoverable, người dùng nhập lệnh tiếp ngay. Với lỗi fatal, Client tự đóng kết nối và người dùng **chỉ cần gõ lại `connect`** để tạo phiên mới, không cần thoát và chạy lại Client.

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
| `Server error SERVER_BUSY: ...` | Server đã đạt giới hạn kết nối (`max_clients`, mặc định 10). Thường hiện ở lệnh đầu tiên sau `connect`. Client tự đóng kết nối, không gửi dữ liệu file. Chờ một lúc rồi gõ lại `connect` |
| `Server error CHECKSUM_MISMATCH: ...` | Dữ liệu upload bị sai khi tới server. Server giữ nguyên file cũ, phiên vẫn mở, thử upload lại |
| `CHECKSUM_MISMATCH: received file bytes differ...` | File tải về sai checksum. Client xóa file tạm, **không ghi đè** file cũ, đóng kết nối. Dùng `connect` rồi thử lại |
| `Cannot read local file ...` | File local đang bị chương trình khác khóa hoặc không đọc được. Client chưa gửi gì lên server, phiên vẫn mở. Đóng chương trình đang dùng file rồi thử lại |
| `CONNECTION_OR_IO_ERROR: connection lost during upload/download after X of Y bytes ...` | Mất kết nối giữa lúc truyền (mã là `TIMEOUT:` nếu quá hạn chờ dữ liệu). Lượt truyền bị đánh dấu `FAILED`, file tải dở bị xóa. Dùng `connect` để tạo phiên mới và truyền lại từ đầu |
| `... the result is unverified` | Mất kết nối sau khi gửi hết dữ liệu nhưng trước khi server xác nhận. Không biết server đã lưu hay chưa: dùng `connect`, `list` để kiểm tra rồi upload lại nếu cần |
| `TIMEOUT: no response from server within N s. Connection closed; ...` | Server không phản hồi trong N giây, với N là `socket_timeout` của Client (mặc định 30). Client đóng kết nối. Gõ lại `connect` |
| `CONNECTION_OR_IO_ERROR: Server closed the connection. Connection closed; ...` | Server đóng kết nối mà không gửi thông báo lỗi. Client không coi đó là thành công. Gõ lại `connect` |
| `CONNECTION_OR_IO_ERROR: ...` (các nội dung khác) | Lỗi socket hoặc ổ đĩa do Client tự phát hiện (bị reset, ngắt mạng, không ghi được file). Lượt truyền đang chạy bị `FAILED`. Gõ lại `connect` |

Client phân loại lỗi của server thành hai nhóm:

| Nhóm | Mã lỗi | Hành vi của client |
| --- | --- | --- |
| Recoverable | `INVALID_COMMAND`, `INVALID_FILENAME`, `INVALID_FILE_SIZE`, `FILE_TOO_LARGE`, `INVALID_CHECKSUM`, `CHECKSUM_MISMATCH`, `FILE_NOT_FOUND`, `FILE_BUSY` | Báo lỗi, giữ kết nối, có thể gõ lệnh tiếp |
| Fatal | `SERVER_BUSY`, `TIMEOUT`, `TRANSFER_INCOMPLETE`, `CONNECTION_OR_IO_ERROR`, `INVALID_HEADER`, `HEADER_TOO_LARGE` và mọi mã lạ chưa biết | Báo lỗi, tự đóng socket, cần chạy lại `connect` |

`TIMEOUT` và `CONNECTION_OR_IO_ERROR` có hai dạng hiển thị: do Server báo thì hiện `Server error TIMEOUT: ...`, do chính Client phát hiện thì hiện `TIMEOUT: ...` hoặc `CONNECTION_OR_IO_ERROR: ...`. Cả hai đều fatal.

Khi không chắc server còn giữ kết nối hay không, client chọn đóng socket cho an toàn.

Nếu Server đã đóng một kết nối nhàn rỗi mà Client chưa biết, lệnh `connect` sẽ báo `Already connected`. Hãy gõ một lệnh bất kỳ (ví dụ `list`) để Client phát hiện kết nối đã mất, rồi gõ lại `connect`.

Ví dụ các tình huống lỗi (kích thước, mã lỗi và thông báo lấy từ lần chạy thử):

```text
> connect 192.168.1.10 5000
Connected to server.
> list
Error: Server error SERVER_BUSY: Server has reached max_clients limit. The server is overloaded; wait a moment, then try again. Connection closed; use 'connect' to reconnect.
> connect 192.168.1.10 5000
Connected to server.
```

```text
> upload report.pdf
Uploading report.pdf
Size: 2.9 KiB
Error: Server error FILE_BUSY: File is currently in use. Another transfer is using this file; try again later
> list
Files on server (1):
  report.pdf
```

```text
> download data.bin
Downloading data.bin
Error: CONNECTION_OR_IO_ERROR: connection lost during download after 4000 of 10000 bytes (Peer disconnected before all file bytes arrived). Transfer FAILED; partial data discarded.
> list
Error: Not connected. Use: connect <ip> [port]
```

Với `FILE_BUSY` Client không gửi dữ liệu file và phiên vẫn mở. Với mất kết nối giữa lúc tải, file `.part` bị xóa và file cũ trong `client_data/downloads/` (nếu có) được giữ nguyên.

## 9. Hành vi cần biết

- Upload ghi đè file trùng tên trên server.
- Download ghi đè file trùng tên trong `client_data/downloads/`. Dữ liệu được ghi vào file `.part` rồi mới đổi tên khi tải xong, nên tải hỏng không để lại file dở.
- Server xử lý nhiều client đồng thời, tối đa `max_clients` kết nối (mặc định 10). Client nhàn rỗi vẫn chiếm một slot cho tới khi `quit`, mất kết nối hoặc hết timeout (mặc định 30 giây). Kết nối vượt giới hạn bị từ chối bằng `SERVER_BUSY`.
- Mỗi tên file chỉ được dùng bởi một lượt truyền (upload hoặc download) tại một thời điểm. Client thứ hai truy cập cùng tên file sẽ nhận `FILE_BUSY` ngay (phiên vẫn mở, không mất dữ liệu). Các tên file khác nhau được truyền song song.
- File upload được server lưu trong `src/server/storage/` (mặc định, theo `configs/server.json`).
- Client chỉ in `SHA-256 MATCH` khi server đã xác nhận checksum khớp. Thiếu hoặc sai checksum thì lượt truyền bị coi là thất bại.
- File tải về chỉ xuất hiện trong `client_data/downloads/` sau khi nhận đủ byte và checksum đúng. Nếu lỗi, file tạm `.part` bị xóa và file cũ (nếu có) được giữ nguyên.
- Client không tự động thử lại. Khi lỗi giữa chừng, người dùng tự chạy `connect` và gõ lại lệnh.

## 10. Ghi kết quả CSV

Mỗi lần upload/download đều ghi một dòng vào file CSV (mặc định `results/raw/baseline.csv`):

- Thành công: `status = SUCCESS`, `checksum_match = true`, có `throughput_mbps`.
- Thất bại: `status = FAILED`, `error_message` ghi nguyên nhân, `throughput_mbps` để trống. Lượt truyền chưa được server xác nhận checksum không bao giờ có throughput hợp lệ.
- Lỗi do Client tự phát hiện có `error_message` bắt đầu bằng mã (`TIMEOUT:` hoặc `CONNECTION_OR_IO_ERROR:`). Lỗi do Server báo có dạng `Server error <MÃ>: ...`.

## 11. Chạy nhiều client cùng lúc để test

Mỗi client là **một tiến trình riêng** (mỗi cửa sổ terminal một lần chạy). Không dùng một `FileClient` từ nhiều thread cùng lúc: nếu làm vậy client báo `RuntimeError` (có thể chuyển giao client cho thread khác, miễn là không dùng đồng thời). Hãy cho mỗi instance thư mục tải và file CSV riêng để các lần chạy không đè lên nhau:

```powershell
python -m src.client.client --download-dir client_data/downloads_1 --csv results/raw/client1.csv
python -m src.client.client --download-dir client_data/downloads_2 --csv results/raw/client2.csv
```

File CSV không được thiết kế cho nhiều tiến trình ghi cùng lúc, nên đừng dùng chung một file `--csv`.

Khi nhiều client cùng upload, mỗi client nên dùng tên file khác nhau. Hai client cùng truy cập một tên file sẽ nhận `FILE_BUSY` (recoverable).

**Dùng `FileClient` từ script (ví dụ `scripts/run_concurrent.py`).** Mỗi worker tạo một `FileClient` riêng, không chia sẻ giữa các thread. Các tham số của hàm khởi tạo:

| Tham số | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `csv_path` | `results/raw/baseline.csv` | File CSV ghi kết quả của Client này |
| `download_dir` | `client_data/downloads` | Thư mục tải về, mỗi Client một thư mục riêng |
| `num_clients` | `1` | Số client trong lần chạy, ghi vào CSV |
| `client_id`, `session_id` | `None` | Định danh ghi vào CSV khi được truyền |
| `csv_fields` | `None` | Danh sách cột CSV (runner dùng bộ cột mở rộng) |
| `socket_timeout` | `30` | Số giây tối đa chờ Server; quá hạn thì báo `TIMEOUT` |
| `environment_id`, `chunk_size`, `auto_environment`, `results_dir` | xem mã nguồn | Như Sprint 1 |

Các tham số này được khóa bằng `tests/test_client_runner_compat.py`: nếu runner hoặc Client đổi chữ ký mà làm lệch nhau, test sẽ báo lỗi.

## 12. Kiểm thử tự động

Chạy tại thư mục gốc project (venv đã kích hoạt):

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

Các file test của Client:

| File | Dùng gì | Kiểm tra |
| --- | --- | --- |
| `tests/test_client_reliability.py` | Server giả | Từng mã lỗi, `.part`, checksum, CSV `FAILED`, khóa thao tác, reconnect |
| `tests/test_client_real_server.py` | `FileServer` và Storage thật, TCP proxy cắt kết nối | `SERVER_BUSY`, `FILE_BUSY` rồi `LIST` và retry, upload/download bị ngắt giữa chừng, reconnect, hồi quy Sprint 1 |
| `tests/test_client_runner_compat.py` | Runner thật, Server giả | Chữ ký `FileClient` khớp với `scripts/run_concurrent.py`, cổng READY, dòng CSV `FAILED` |
| `tests/test_client_timeout_label.py` | Server im lặng | Thông báo `TIMEOUT` nêu đúng `socket_timeout` của từng Client |

Nếu `tests/test_server.py::ConfigTests::test_cli_overrides_json_and_resolves_paths` báo lỗi trên máy có tên người dùng Windows chứa dấu cách (đường dẫn dạng `HITCC~1`), đó là lỗi môi trường của test Server, không liên quan Client.

## 13. Kịch bản kiểm thử lỗi trên hai máy

Máy Server chạy Server, máy Client chạy Client (xem mục 7). Mỗi Client chạy ở một cửa sổ terminal riêng và dùng `--csv` và `--download-dir` riêng (mục 11). Lệnh `Get-FileHash`, `Import-Csv`, `Get-ChildItem` gõ ở PowerShell, còn `connect`, `upload`, `download`, `list`, `quit` gõ ở dấu nhắc `>` của Client.

| Ca | Cách làm | Kết quả đúng |
| --- | --- | --- |
| `SERVER_BUSY` | Chạy Server với `--max-clients 2 --client-timeout 120`. Mở 2 Client, mỗi Client `connect` rồi `list` và để nguyên. Client thứ 3 `connect` rồi `list` và `upload` | `connect` vẫn báo `Connected to server.`. `list` và `upload` báo `Server error SERVER_BUSY`, Client tự đóng kết nối, không in `SHA-256 MATCH`, Server không có file mới, CSV `FAILED` không có throughput. Một Client `quit` thì Client thứ 3 gõ lại `connect` và dùng được |
| `FILE_BUSY` | Client A upload file lớn (vài trăm MiB). Trong lúc đó Client B upload file cùng tên rồi gõ `list` | B báo `Server error FILE_BUSY`, không gửi dữ liệu file, `list` chạy ngay trên cùng kết nối. Khi A xong, B upload lại thành công. CSV của B có dòng `FAILED` rồi `SUCCESS` |
| Upload bị ngắt | Upload file lớn, ngắt mạng ở máy Client giữa lúc truyền | Báo `CONNECTION_OR_IO_ERROR` hoặc `TIMEOUT`, không in `SHA-256 MATCH`, CSV `FAILED`. Sau khoảng 30 giây Server không còn file dở, không còn file `.part`, và log Server có dòng `INCOMPLETE` hoặc `TIMEOUT` của lượt truyền đó. `connect` lại và upload lại thành công |
| Download bị ngắt | Tải một file hoàn chỉnh trước, ghi lại hash. Tải lại và ngắt mạng giữa chừng | Báo lỗi, không in `SHA-256 MATCH`, file `.part` bị xóa, hash của file cũ không đổi, CSV `FAILED`. `connect` lại và tải lại thành công |

Cách ngắt mạng: bật Airplane mode của Windows hoặc dùng `Disable-NetAdapter` và `Enable-NetAdapter` (cần PowerShell chạy bằng Administrator). Chỉ ngắt ở máy Client, không tắt Server.

## 14. Giới hạn hiện tại

- Chưa có TLS: dữ liệu truyền qua mạng **không được mã hóa**. Không dùng để truyền dữ liệu nhạy cảm.
- Chưa có resume, tự động thử lại, progress bar nâng cao, đăng nhập và GUI. Mỗi Client chỉ thực hiện một lượt truyền tại một thời điểm; muốn truyền song song thì chạy nhiều Client.
