# CN21-13 — Trạng thái và kế hoạch sau tích hợp

Cập nhật **26/11/2026**. Thay đổi chỉ trên `ha-nguyet`; `main` và các nhánh thành viên không bị sửa. Nền main được đồng bộ: `3c5373116525d6eb52c125d808eef7343026dd8a`.

## 1. Dependency đã mở khóa

| Thành phần | Trạng thái GitHub |
| --- | --- |
| PR #7 — Storage locked(...) | MERGED 26/11 |
| PR #9 — Server concurrent/FILE_BUSY | MERGED 26/11 |
| PR #8 — Client Reliability | MERGED 26/11 |
| PR #6 — Runner + Client integration | MERGED 26/11 từ ha-nguyet-s2-concurrent |
| PR #10 — Client với Server thật | OPEN; chưa đưa source PR đang mở vào bản này |

Việc chờ PR #8 đã hoàn tất. Main đã giải quyết ghép Client Reliability với optional constructor fields của runner. Nhánh ha-nguyet đồng bộ bản ghép đó, giữ thêm validate_worker_rows và các test/metadata/mẫu lịch sử riêng đã có ngày 22–23/11. Không rebase/force-push lịch sử đã được chia sẻ; đồng bộ bằng merge để giữ cả hai lịch sử và các cập nhật đã review.

## 2. Thực hiện trong nhánh ha-nguyet

- Giữ nguyên src/client/client.py từ main 3c53731: SERVER_BUSY fatal, FILE_BUSY recoverable, exclusive operations, reconnect và download an toàn; đồng thời có num_clients/client_id/session_id/csv_fields/socket_timeout.
- Giữ nguyên source Server/Storage/Protocol từ main: khóa qua locked(filename, owner=connection_id), release_all và worker manager như nhóm đã merge.
- Giữ các kiểm tra CSV của ha-nguyet: fixture byte size, UUID/timezone, context IDs, num_clients, metric, lý do FAILED.
- Test runner dùng Server/Storage production mặc định; SequentialFileServer chỉ là đối chứng âm. Loại bỏ cấu hình trùng max_clients trong test sau khi ServerConfig đã có field thật.
- Giữ nguyên baseline Sprint 1 và các mẫu lịch sử 22–23/11. Không lấy mẫu main 18/11 ghi đè mẫu riêng hoặc đổi ngày đo.
- README Windows chuyển sang một checkout cho cả Server và runner; không cần hai nhánh/thư mục feature như trước.

## 3. Trình tự kiểm chứng

1. Full regression của checkout tích hợp bằng pytest.
2. Chạy 1/5/10 client, upload/download ba fixture, kiểm tra 6/30/60 dòng, checksum và overlap.
3. Kiểm tra byte file thực tế ở nguồn, Server và từng thư mục download; metadata có nguồn main và source hashes.
4. Kiểm tra diff để source Client/Server/Storage/Protocol vẫn đúng main, baseline cũ giữ nguyên.
5. Cập nhật kết quả trong [sprint2-integration-verification.md](sprint2-integration-verification.md), chỉ push ha-nguyet.

## 4. Phần còn để lại

- Review phần CSV bổ sung trên ha-nguyet; PR #6 đã merge không có nghĩa các commit riêng ngày 22–23/11 tự xuất hiện trong main.
- PR #10 còn OPEN: lỗi timeout label và các test Client với Server thật nằm ở nhánh Client; không tự lấy hoặc sửa thay owner.
- Review PR #9 có nhận xét P1 về worker.start() thất bại có thể làm dừng accept loop khi hết tài nguyên thread. Chưa tái hiện/chỉnh trong phạm vi CN21-13; cần owner Server xử lý hoặc Team Lead chấp nhận giới hạn.
- Windows/Python 3.11 và LAN PC Server Ethernet → laptop Wi-Fi vẫn cần bằng chứng thực tế do nhóm điều phối. Kết quả Linux/Python 3.11 không thay Windows/LAN.
- Team Lead review và chốt trạng thái cuối; chưa có đủ bằng chứng chuyển toàn bộ Sprint 2 thành ACCEPTED/DONE.

## 5. Lịch điều phối

Mốc nhóm trưởng: Backend 25/11, review Backend 26/11; Client 28/11; CN21-13 29/11. Dependency merge được xác nhận bằng trạng thái PR thực tế, không bằng ngày dự kiến. Các bước đã mở khóa đã được thực hiện; nghiệm thu còn thiếu giữ PENDING.
