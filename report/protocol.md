# Application protocol — Sprint 1

## Framing

- TCP stream gồm header JSON UTF-8 kết thúc bằng một byte LF (`\n`). Command phân biệt hoa/thường.
- Request header tối đa 65536 byte, tính cả LF; không dùng pretty-print JSON nhiều dòng.
- Nội dung file là binary nguyên bản, truyền đúng `file_size` byte, không có delimiter bổ sung.
- `recv()` có thể trả về một phần header/payload hoặc nhiều frame cùng lúc. Hai phía phải giữ buffer và đọc theo độ dài.
- Sau một command thành công, cùng kết nối có thể tiếp tục nhận command tiếp theo.
- Header của `LIST` có thể dài hơn giới hạn request vì chứa toàn bộ danh sách file.
- Field dư được bỏ qua. Giá trị `command` phải là một trong `UPLOAD`, `DOWNLOAD`, `LIST`, `QUIT`.

Mọi dòng JSON dưới đây đều có LF ở cuối. Các dòng mô tả binary không phải dữ liệu gửi trên mạng.

## UPLOAD

Client gửi metadata:

```json
{"command":"UPLOAD","filename":"sample.bin","file_size":4}
```

Server kiểm tra metadata và tạo file tạm trước khi trả lời:

```json
{"status":"READY","command":"UPLOAD","filename":"sample.bin","file_size":4}
```

Client chỉ gửi payload sau khi nhận `READY`, ở ví dụ này là đúng 4 byte.
Server ghi theo chunk và chỉ commit file khi nhận đủ số byte dự kiến:

```json
{"status":"SUCCESS","command":"UPLOAD","filename":"sample.bin","file_size":4}
```

- `file_size` phải là số nguyên không âm; boolean, chuỗi và số thực bị từ chối.
- File rỗng (`file_size = 0`) vẫn có đủ hai response `READY` và `SUCCESS`, không có payload.
- Filename là tên file đơn, không chứa đường dẫn, ký tự điều khiển hoặc ký tự không hợp lệ trên Windows. Tên tối đa 255 byte UTF-8; tên thiết bị Windows, dấu chấm/khoảng trắng ở cuối, `.uploads` và `.gitkeep` bị từ chối.
- Symlink và thư mục không được dùng làm file đích.
- Upload thành công ghi đè file trùng tên. Upload chưa hoàn tất giữ file cũ và xóa file tạm khi xử lý kết thúc.
- Nếu metadata bị từ chối, client không gửi payload và có thể gửi command khác.
- Nếu gửi ít byte rồi đóng kết nối, server log `INCOMPLETE`. Nếu chờ quá lâu, server log `TIMEOUT` và đóng kết nối.
- Byte dư sau `file_size` được xem là đầu của request tiếp theo. TCP không cung cấp ranh giới file ngoài độ dài đã khai báo.

## DOWNLOAD

```json
{"command":"DOWNLOAD","filename":"sample.bin"}
```

Server gửi metadata, đúng số byte payload, sau đó gửi completion header:

```json
{"status":"OK","command":"DOWNLOAD","filename":"sample.bin","file_size":4}
```

`<4 binary bytes>`

```json
{"status":"SUCCESS","command":"DOWNLOAD","filename":"sample.bin","file_size":4}
```

Client đọc đúng `file_size` byte trước khi parse JSON tiếp theo. Không được dùng
newline hoặc chuỗi `SUCCESS` để tìm điểm kết thúc binary. Nếu kết nối đóng trước
khi đủ payload hoặc trước completion header, client phải coi download thất bại.
`SUCCESS` nghĩa là server đã gửi đủ byte vào socket; không phải xác nhận client
đã lưu file xuống ổ đĩa.

File không tồn tại không có payload hay completion header:

```json
{"status":"ERROR","code":"FILE_NOT_FOUND","message":"Requested file does not exist"}
```

## LIST

```json
{"command":"LIST"}
```

```json
{"status":"OK","command":"LIST","files":["image.jpg","sample.bin","test.pdf"]}
```

Danh sách sắp xếp theo tên; storage rỗng trả về `[]`. Chỉ liệt kê file thường có
tên hợp lệ, không liệt kê symlink, thư mục, `.gitkeep` hoặc file tạm trong `.uploads/`.

## QUIT

```json
{"command":"QUIT"}
```

```json
{"status":"OK","command":"QUIT"}
```

Server đóng kết nối client sau response và quay lại `accept()`.

## Errors

Response lỗi có `status = ERROR`, `code` và `message`.

| Code | Ý nghĩa | Kết nối |
| --- | --- | --- |
| `INVALID_COMMAND` | Command thiếu hoặc không được hỗ trợ | Tiếp tục |
| `INVALID_FILENAME` | Tên hoặc loại file đích không hợp lệ | Tiếp tục |
| `INVALID_FILE_SIZE` | Kích thước thiếu hoặc không hợp lệ | Tiếp tục |
| `FILE_TOO_LARGE` | Upload vượt `max_file_size` | Tiếp tục |
| `FILE_NOT_FOUND` | Không tìm thấy file download | Tiếp tục |
| `INVALID_HEADER` | JSON/UTF-8 không hợp lệ hoặc JSON không phải object | Đóng |
| `HEADER_TOO_LARGE` | Request header quá giới hạn | Đóng |
| `TIMEOUT` | Socket không tiến triển trong thời gian cấu hình | Đóng |
| `TRANSFER_INCOMPLETE` | Số byte ghi không khớp metadata | Đóng |
| `CONNECTION_OR_IO_ERROR` | Socket hoặc thao tác file bị lỗi | Đóng |

Khi download đang gửi binary mà lỗi, server đóng kết nối và ghi log, không chèn
JSON lỗi vào payload đang dang dở. Nếu peer đã ngắt/reset kết nối, response lỗi có
thể không gửi được. Lỗi của một client không dừng vòng lặp nhận client tiếp theo.
