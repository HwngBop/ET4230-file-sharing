# Mẫu nghiệm thu Sprint 2

Kết quả từ ba phiên CLI chạy thật ngày 21/11/2026 trên cùng máy Linux/Python 3.12.14, server `cn21-10` tại `a07b950`, max_clients=10, buffer hai phía 65536 byte. Mỗi client upload/download ba file đúng 1.000.000, 10.000.000 và 50.000.000 byte.

| Thư mục | Client | Dòng CSV | Kết quả |
| --- | --- | --- | --- |
| clients-1 | 1 | 6 | PASS |
| clients-5 | 5 | 30 | PASS |
| clients-10 | 10 | 60 | PASS |

CSV giữ nguyên UUID, timestamp, thời lượng, checksum và throughput do runner tạo. Summary chứa các mốc READY, payload release và completion cùng kết quả từng worker. Runner log được ghi tự động. Metadata công khai đã bỏ CPU/RAM/số lõi/phạm vi hardware; ghi rõ thông tin đã lược bỏ thay vì thay bằng dữ liệu giả. Chỉ có địa chỉ loopback, không có IP LAN/hostname hoặc đường dẫn cục bộ.

Code có thay đổi chưa commit khi đo; metadata giữ commit nền và source_sha256 của từng file thực thi. Các hash này cần khớp code được dùng để tái lập. Thu thập metadata đầy đủ trên từng máy khi đo lại.

Test-suite.log trích dòng unittest từ lần chạy 54 test trên nhánh ha-nguyet với implementation server a07b950. Stdout có đường dẫn tạm được bỏ khỏi bản trích. Test FILE_BUSY giả lập response có kiểm soát để kiểm tra client recovery; không chứng minh storage production đã có khóa file.

Upload đầu tính thời gian chờ gate READY, dùng để nghiệm thu concurrency. Mẫu localhost không thay baseline LAN/Windows và không dùng làm tốc độ card mạng. Xem [README](../../README.md) và [test plan](../../report/sprint2-test-plan.md).
