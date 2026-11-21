# Client CLI — Sprint 1 và measurement

Client Python 3.11.x dùng TCP, hỗ trợ upload/download/list/quit, kiểm tra SHA-256 và ghi CSV tự động. Hướng dẫn Windows cho runner nhiều client: [README](../README.md).

## Chạy trên Windows

Mở cmd tại thư mục gốc nhánh `ha-nguyet` (nơi có src/scripts):

```bat
py -3.11 src/client/client.py
```

Không cần cài editable hoặc pyproject.toml. Client cốt lõi chỉ dùng thư viện chuẩn.

## Các lệnh trong client

```text
connect 127.0.0.1 5000
upload test_files/sprint2/test_1MB.bin
list
download test_1MB.bin
quit
```

Thay 127.0.0.1 bằng IPv4 thật của server khi chạy hai máy. Không kết nối đến 0.0.0.0. Upload chấp nhận đường dẫn tương đối/tuyệt đối; đường dẫn có khoảng trắng đặt trong dấu ngoặc kép. Nếu chỉ nhập tên file, client tìm trong thư mục hiện tại rồi client_data/uploads. Download chỉ nhận tên file đơn và lưu vào client_data/downloads.

| Lệnh | Ý nghĩa |
| --- | --- |
| connect IP [port] | Kết nối TCP, port mặc định 5000 |
| upload file | Gửi file, kiểm tra checksum và ghi CSV |
| download filename | Nhận vào .part, xác minh trước khi đổi sang file đích |
| list | Danh sách file trên server |
| quit | Đóng phiên đúng giao thức và thoát |
| help | Danh sách lệnh |

## Kết quả và CSV

Màn hình hiển thị SHA-256 MATCH, thời gian giây và application throughput **Mbps**. Không dùng MB/s làm metric của dự án. CSV mặc định results/raw/baseline.csv; tùy chọn `--csv` chọn file khác, `--environment` chọn metadata đã ghép.

```bat
py -3.11 src/client/client.py --csv results/raw/manual.csv --environment results/environment.json
```

SUCCESS chỉ khi đủ byte, completion đúng và SHA-256 khớp. Lỗi ghi FAILED, throughput trống. Mỗi lượt có UUID; LIST/QUIT không tạo dòng transfer. Các con số ví dụ trong tài liệu không phải dữ liệu đo.

## Server và lỗi

Server đi kèm ha-nguyet là tuần tự. Muốn 5/10 client phải khởi động server cn21-10 theo README. Metadata tự thu thập không xác định được server thì ghi unknown; để nghiệm thu cần export riêng trên từng máy.

- Connection refused/timeout: kiểm tra LISTENING, IP/port và firewall.
- FILE_NOT_FOUND: dùng list hoặc kiểm tra đường dẫn upload.
- FILE_BUSY: lượt truyền FAILED; kết nối có thể dùng tiếp khi server trả lỗi recoverable. Không tự retry vô hạn.
- Checksum mismatch: giữ kết quả lỗi và kiểm tra nguồn có đổi trong khi truyền.
- Lỗi protocol/socket nghiêm trọng: kết nối đóng, cần connect lại.

Upload thành công có thể ghi đè file cùng tên trên server; download thành công có thể thay file cùng tên trong thư mục download. Không có TLS, đăng nhập, GUI hay resume. SHA-256 là kiểm tra toàn vẹn, không phải mã hóa hoặc xác thực.
