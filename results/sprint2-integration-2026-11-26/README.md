# Kiểm chứng sau đồng bộ main — 26/11/2026

Nhánh ha-nguyet đồng bộ main tại 3c53731, giữ kiểm tra CSV bổ sung. Server, Storage, Client Reliability và Protocol dùng đúng source main đã merge; không lấy source PR #10 đang mở.

- Full project regression: **141 tests PASS** trên Linux/Python **3.11.17**, và **141 tests PASS** trên Linux/Python **3.12.14**.
- CLI thật trên mỗi phiên bản Python: 1/5/10 client, mỗi client upload/download 1/10/50 MB, tương ứng 6/30/60 dòng. Tất cả SUCCESS/checksum true; gate và overlap PASS.
- clients-1/5/10 lưu CSV/summary/runner log/metadata thật của Python 3.11.17. run-matrix.json ghi cả sáu phiên; dữ liệu Python 3.12 gốc giữ cục bộ.
- Metadata công khai đã bỏ CPU/RAM cụ thể; chỉ chứa địa chỉ loopback, source hashes và main reference. Code chưa commit lúc đo, nên giữ working_tree_dirty và commit nền; source hashes xác định file thực thi.
- Đã đọc lại và so hash ở nguồn, upload worker, file nhận Server và download cho 96 cặp file qua hai phiên bản Python; không chèn số benchmark thủ công.

Kết quả Linux/Python 3.11 không thay nghiệm thu Windows/Python 3.11 hoặc LAN Ethernet/Wi-Fi. Upload đầu có gate wait, không so như baseline throughput thuần Sprint 1. Các mẫu ngày 18/22/23 là dữ liệu lịch sử; không sửa timestamp/số liệu để giả làm kết quả sau tích hợp.

Chi tiết: [report/sprint2-integration-verification.md](../../report/sprint2-integration-verification.md).
