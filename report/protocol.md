# ET4230 — Application Protocol Specification

**Phiên bản:** Sprint 1 Review, v1.1 (ngày 11/11/2026)  
**Đối tượng:** Client CLI ↔ Server TCP; một kết nối phục vụ tuần tự các command  
**Nguồn:** `src/common/protocol.py`, `src/server/server.py`, `src/client/client.py` của bản sửa đi kèm

> Đây là đặc tả **phiên bản code đã chỉnh sửa**. Trước bản này, repo `main` dùng cùng cơ chế newline JSON và length-delimited payload nhưng chưa tích hợp checksum end-to-end. Không sử dụng thiết kế 4-byte header prefix cũ nữa.

## 1. Mô hình và tầng giao thức

```text
┌──────────── CLIENT ────────────┐             ┌──────────── SERVER ────────────┐
│ CLI (connect/upload/download)  │             │ Command dispatcher            │
│ JSON metadata + SHA-256        │  TCP/IPv4   │ JSON metadata + SHA-256        │
│ Chunk sender / receiver        ├─────────────┤ Chunk receiver / sender       │
│ Download .part + rename        │             │ Storage + temp upload + rename│
└────────────────────────────────┘             └────────────────────────────────┘
```

Application Protocol → TCP reliable, ordered **byte stream** → IP. TCP không đảm bảo ranh giới thông điệp: một `recv()` có thể trả về ít byte hơn yêu cầu, gộp nhiều JSON frame, hoặc kèm một phần payload. Hai phía phải dùng **cùng một `Connection` instance** cho toàn bộ socket và chuyển từ header sang payload dựa trên `file_size`.

## 2. Framing — chuẩn wire format

- Header là **JSON object** mã hóa UTF-8, dạng một dòng duy nhất, kết thúc bằng **một byte LF (`0x0A`, `\n`)**.
- Mỗi header tối đa **65.536 bytes (64 KiB)**, **bao gồm** LF. Header nhiều dòng/pretty JSON không được dùng.
- Khi header mô tả `file_size > 0`, ngay sau LF là đúng `file_size` bytes binary gốc. Không thêm delimiter, base64, ký tự xuống dòng hay dấu kết thúc vào binary payload.
- Sau khi nhận **đủ** `file_size` bytes, mới được gọi `receive_header()` để đọc frame kế tiếp.
- Mỗi chiều sử dụng chuỗi request/response được quy định bên dưới; một TCP connection có thể xử lý nhiều command tuần tự, trừ khi lỗi fatal.
- Cả Client và Server trong bản sửa dùng giới hạn header 64 KiB. Nếu danh sách `LIST` quá dài, Server trả `HEADER_TOO_LARGE` và đóng kết nối; phân trang `LIST` là một hướng mở rộng tương lai.

```text
TCP stream:
  {JSON metadata}\n [optional raw file bytes] {next JSON metadata}\n ...
```

`Connection.receive_header()` duy trì `buffer` cho bytes đã nhận dư. `Connection.receive_chunk(maximum)` ưu tiên đọc bytes còn trong buffer rồi mới gọi `socket.recv()`; hàm **có thể trả về ít hơn** `maximum`, nhưng tối thiểu một byte hoặc ném exception khi kết nối bị ngắt. Chỉ gọi khi `maximum >= 1`.

## 3. Kiểu dữ liệu, metadata và giới hạn

| Field | Kiểu dữ liệu | Ý nghĩa |
| --- | --- | --- |
| `command` | string | Request, case-sensitive: `UPLOAD`, `DOWNLOAD`, `LIST`, `QUIT` |
| `status` | string | Response: `READY`, `OK`, `SUCCESS`, `ERROR` |
| `filename` | string | Tên file đơn, không chứa path, tối đa 255 byte UTF-8 |
| `file_size` | integer ≥ 0 | Số **byte** của binary payload; không chấp nhận boolean |
| `sha256` | string | SHA-256 hexadecimal 64 ký tự, hash của toàn bộ file |
| `files` | array of strings | Danh sách file từ `LIST` |
| `code` | string | Mã lỗi trong response `ERROR` |
| `message` | string | Thông báo lỗi cho người dùng |

Default server: TCP port **5000**, `chunk_size = 65536 bytes (64 KiB)`, `client_timeout = 30 s`, `max_file_size = 1,073,741,824 bytes (1 GiB)`. Các giá trị này cấu hình ở `configs/server.json`. Chunk size hiện tại là **buffer xử lý của chương trình**, không phải một frame truyền riêng trên TCP và không đồng nghĩa với số byte mỗi gói TCP trên mạng.

Kiểm tra filename trên Server: từ chối tên rỗng, `.`/`..`, separator đường dẫn, ký tự không hợp lệ, tên thiết bị Windows, dấu chấm/khoảng trắng cuối, symlink và thư mục; không cho truy cập ra ngoài storage directory. `UPLOAD` thành công có thể ghi đè file trùng tên.

## 4. UPLOAD

**4.1 Client → Server (header)**

```json
{"command":"UPLOAD","filename":"sample.bin","file_size":4,"sha256":"...64-hex-characters..."}
```

Client phiên bản v1.1 **luôn tính SHA-256 trước** và gửi trong header. Server chấp nhận field `sha256` **không có** để tương thích script/test cũ, nhưng khi thiếu thì Server không có hash nguồn để kiểm tra và không được tuyên bố đã kiểm chứng tính toàn vẹn giữa nguồn và đích. Nếu có `sha256`, Server yêu cầu đúng 64 ký tự hex; từ chối trước khi `READY` nếu sai.

**4.2 Server → Client (READY)**

```json
{"status":"READY","command":"UPLOAD","filename":"sample.bin","file_size":4}
```

Server xác minh filename, file_size, giới hạn dung lượng, định dạng SHA-256 và mở file tạm trước khi trả `READY`. Client **chỉ gửi payload khi nhận `READY`**.

**4.3 Client → Server (4 bytes ví dụ)**

```text
00 FF 0A 58
```

Server đọc đúng `file_size` bytes trong các chunk, cập nhật SHA-256 streaming, ghi vào file tạm `.uploads/*.part`. Nếu hash khác giá trị nguồn, trả `ERROR/CHECKSUM_MISMATCH`, xóa file tạm, **không ghi đè file đích cũ**. Nếu đủ byte và hash khớp, file tạm được rename/replace và Server trả:

```json
{"status":"SUCCESS","command":"UPLOAD","filename":"sample.bin","file_size":4,"sha256":"<actual-64-character-hex-hash>"}
```

Client kiểm tra `sha256` trả về khớp với hash nguồn rồi mới in `SHA-256 MATCH`. File rỗng có `file_size=0`, không có binary payload nhưng vẫn `READY` và `SUCCESS` với SHA-256 của chuỗi rỗng.

**Lưu ý thời gian:** Client tính hash file nguồn trước thời điểm bắt đầu đo transfer; số đo completion time không bao gồm giai đoạn tiền xử lý này. Server tính hash streaming trong lúc ghi file. Điều này cần mô tả rõ ở phần benchmark.

## 5. DOWNLOAD

**5.1 Client → Server**

```json
{"command":"DOWNLOAD","filename":"sample.bin"}
```

**5.2 Server → Client (metadata)**

```json
{"status":"OK","command":"DOWNLOAD","filename":"sample.bin","file_size":4}
```

**5.3 Server → Client (exactly file_size binary bytes)**

```text
00 FF 0A 58
```

**5.4 Server → Client (completion header)**

```json
{"status":"SUCCESS","command":"DOWNLOAD","filename":"sample.bin","file_size":4,"sha256":"<actual-64-character-hex-hash>"}
```

Server cập nhật SHA-256 trên **chính những byte đã đọc và gửi**. Client cập nhật SHA-256 trên những byte đã nhận/ghi vào `.part`, và **chỉ đổi `.part` sang file đích khi** đủ `file_size`, có `SUCCESS` và hash khớp. Nếu không đủ payload, `SUCCESS` không đến hoặc hash sai, Client xóa `.part`, coi transfer thất bại và không thay file download cũ.

`SUCCESS` ở Server thể hiện dữ liệu đã được đưa qua `sendall()` và completion header; **không phải** bằng chứng phía Client đã ghi thành công xuống ổ đĩa. Server không có application ACK xác nhận bước lưu này ở v1.1.

Khi filename không tồn tại, Server trả `ERROR/FILE_NOT_FOUND` (không có payload).

## 6. LIST / QUIT

**LIST:**

```json
{"command":"LIST"}
```

```json
{"status":"OK","command":"LIST","files":["image.jpg","sample.bin"]}
```

Danh sách sắp xếp theo tên, bỏ qua symlink, staging và file không hợp lệ. Header response có giới hạn 64 KiB như các header khác.

**QUIT:**

```json
{"command":"QUIT"}
```

```json
{"status":"OK","command":"QUIT"}
```

Server gửi `OK`, đóng client socket và quay lại vòng lặp `accept()`.

## 7. Error handling

Error response chung:

```json
{"status":"ERROR","code":"FILE_NOT_FOUND","message":"Requested file does not exist"}
```

| Error code | Điều kiện | Kết nối |
| --- | --- | --- |
| `INVALID_COMMAND` | Lệnh không hỗ trợ | Giữ |
| `INVALID_FILENAME` | Tên hoặc đích file không hợp lệ | Giữ |
| `INVALID_FILE_SIZE` | `file_size` sai kiểu/âm | Giữ |
| `FILE_TOO_LARGE` | Upload vượt giới hạn server | Giữ |
| `INVALID_CHECKSUM` | SHA-256 upload không đúng định dạng | Giữ |
| `CHECKSUM_MISMATCH` | Upload đủ byte nhưng hash không khớp | Giữ; file cũ không bị ghi đè |
| `FILE_NOT_FOUND` | Download file không tồn tại | Giữ |
| `INVALID_HEADER` | Header không phải UTF-8 JSON object | Đóng |
| `HEADER_TOO_LARGE` | Header > 64 KiB | Đóng |
| `TIMEOUT` | Không có tiến triển trong timeout | Đóng |
| `TRANSFER_INCOMPLETE` | Số byte ghi không khớp | Đóng |
| `CONNECTION_OR_IO_ERROR` | Lỗi socket/disk | Đóng |

Khi **đang phát payload** mà xảy ra lỗi, Server không được chèn JSON error giữa các byte nhị phân (client có thể hiểu JSON là file). Server đóng kết nối và ghi log. Nếu peer ngắt đột ngột, không thể đảm bảo error response được nhận.

## 8. Phân biệt tin cậy tầng TCP và integrity tầng ứng dụng

TCP đảm bảo luồng byte đúng thứ tự và có cơ chế phát lại ở transport layer. SHA-256 ở application layer giúp kiểm tra **file nguồn và file nhận có cùng nội dung** sau toàn bộ quá trình truyền và lưu. Kiểm tra **đủ số byte** là cần thiết nhưng chưa đủ để phát hiện mọi sai lệch nội dung. SHA-256 không cung cấp encryption, authentication, confidentiality hay bảo vệ trước MITM khi không có cơ chế xác thực bảo mật; dự án chưa triển khai TLS.

## 9. Measurement và kịch bản kiểm thử

**Throughput tầng ứng dụng (Mbps):**

```text
throughput_mbps = file_size_bytes * 8 / (elapsed_seconds * 1_000_000)
```

Phân biệt `Mbps` với `MB/s`, `MB` với `MiB` (1 MiB = 1,048,576 bytes). Client `time.perf_counter()` bắt đầu trước request gửi lên và kết thúc sau completion+checksum; riêng bước đọc hash upload trước request **không tính** trong thời gian này.

**Sprint 1 bắt buộc ghi minh chứng:** upload/download file 10 MiB giữa hai máy thật hoặc hai host khác nhau, log Server, SHA-256 match, một PCAP Wireshark, kết quả thử nghiệm thời gian/throughput. Test loopback chỉ xác nhận logic, không thay bằng chứng mạng hai máy.

**Các test regression đi kèm:** `tests/test_integrity.py` kiểm tra binary upload/download, SHA-256 đúng, mismatch không ghi đè file cũ, invalid checksum không được READY, header oversize. `tests/test_server.py` gốc tiếp tục kiểm tra quy trình Server và các lỗi khác.

**Sprint 2:** multi-client/concurrency, các test chịu tải. **Sprint 3:** thực nghiệm thay đổi `file_size`, `chunk_size`, `number of clients`, `bandwidth` và CSV/plots. **Sprint 4:** báo cáo, demo, bảo vệ, nêu giới hạn thí nghiệm.

## 10. Giới hạn và đóng góp kỹ thuật

- Server v1.1 **tuần tự**, chỉ phục vụ một client đang kết nối; Client 2 có thể đợi client trước đóng/timeout.
- Không có resume, retry application-level, TLS, authentication hay GUI.
- Checksum download tính khi Server gửi và Client nhận; không chứng minh tính toàn vẹn của dữ liệu ở nguồn trước một sự kiện thay đổi file ngoài hệ thống.
- Benchmark về hiệu năng mạng cần điều kiện mạng/cấu hình thiết bị rõ ràng và lặp lại để có nhận định đáng tin cậy; không được suy rộng kết quả LAN sang mọi hệ thống.

**Quy tắc tích hợp:** khi đổi format hoặc sequence response, phải cập nhật **đồng thời** Client + Server + Protocol.md + Tests và thông báo các thành viên. Không thay wire protocol chỉ ở một bên.
