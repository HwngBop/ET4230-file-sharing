# Mẫu Sprint 2 từ chạy thật

Ba phiên loopback trên cùng máy Linux/Python 3.12.14, server concurrent `cn21-10` tại `dd74fe8`, max_clients=10, chunk hai phía=65536 byte. Mỗi client upload/download các file đúng 1.000.000, 10.000.000, 50.000.000 byte.

| Thư mục | Client | Dòng CSV | Kết quả |
| --- | --- | --- | --- |
| clients-1 | 1 | 6 | PASS |
| clients-5 | 5 | 30 | PASS |
| clients-10 | 10 | 60 | PASS |

`all-transfers.csv` giữ nguyên UUID, timestamp, thời lượng và throughput phát sinh từ runner. `summary.json` giữ định danh socket loopback, kết quả từng worker và các mốc chứng minh overlap. `runner.log` là kết quả PASS/FAIL do runner ghi. `environment.json` là bản công khai đã bỏ CPU/RAM/số lõi/phạm vi hardware; không thay hardware bằng số liệu giả. Metadata đầy đủ được tạo khi chạy riêng, tham chiếu environment_id cùng phiên. Không có IP LAN hay hostname trong các mẫu này.

Bản code được đo có working_tree_dirty=true; `source_sha256` xác định các file thực thi cụ thể, cùng commit nền của runner và commit server. Không dùng commit nền đơn lẻ để suy ra toàn bộ code thay đổi chưa commit.

`test-suite.log` trích các dòng unittest từ lần chạy cuối bằng dependency server thật; bỏ stdout tiến trình để tránh đường dẫn tạm không cần thiết. Kết quả 58 tests OK. Các dữ liệu giả lập trong unit test không được đưa vào ba CSV mẫu.

Các lượt upload đầu có thời gian chờ gate READY trong transfer_time_s; đây là mẫu nghiệm thu concurrency, không phải baseline tốc độ LAN hay thống kê benchmark. Không suy rộng throughput loopback sang Wi-Fi/Ethernet. Tài liệu tái lập: `report/sprint2-test-plan.md`.
