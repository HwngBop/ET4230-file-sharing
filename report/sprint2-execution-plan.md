# CN21-13 — Trạng thái và kế hoạch tích hợp

Cập nhật: **23/11/2026**. Phạm vi thay đổi: nhánh `ha-nguyet`, runner/CSV/test và tài liệu CN21-13. Snapshot kiểm tra code: `ha-nguyet` tại `15a234f`, `main` tại `b2e3c98`. Các trạng thái dưới đây là snapshot, cần đọc lại GitHub trước từng bước phụ thuộc.

## 1. Quyết định điều phối mới

Theo thông báo điều phối mới nhất, API thống nhất cho Backend là **`FileStorage.locked(filename, owner=connection_id)`**. Quyết định này thay tên `try_lock_file(filename)` trong bản contract v1.0 ngày 20/11 đối với phần tích hợp sắp tới. Không tự sửa tài liệu frozen của Team Lead hoặc source Server/Storage để ép tương thích.

Thứ tự: Server–Storage hoàn thiện và review → Client Reliability được test với Backend và PR #8 merge → runner tích hợp cuối, giữ tính năng hai phía rồi regression. Không ghép client.py hoặc rebase runner trước khi PR #8 merge.

| Mốc điều phối | Phần việc/owner |
| --- | --- |
| 25/11 | Hiển và Đức chốt Backend locked(filename, owner=connection_id), kiểm tra FILE_BUSY thật |
| 26/11 | Team Lead dự kiến review/merge Backend |
| 28/11 | Client Reliability hoàn thiện và test lại với Backend thật |
| 29/11 | CN21-13 tích hợp runner sau PR #8, kiểm thử và cập nhật kết quả |

Mốc dự kiến không thay bằng chứng PR merged hoặc test PASS thực tế.

## 2. Snapshot GitHub

| Thành phần | Trạng thái quan sát được | Hệ quả cho CN21-13 |
| --- | --- | --- |
| main | b2e3c98, server tuần tự, chưa có Backend/Client Sprint 2 được merge | Chưa dùng làm bản nghiệm thu multi-client tích hợp |
| PR #7, Storage | OPEN; nhánh phuchien123vm-prog-patch-1 tại 6cb967b; có locked(filename, owner=...) | API phía Storage phù hợp hướng mới; chưa coi là Backend đã tích hợp |
| Server cn21-10 | a07b950; vẫn gọi optional try_lock_file, chưa gọi locked(..., owner=connection_id) | Backend chưa sẵn sàng nghiệm thu khóa thật; không sửa thay owner |
| PR #8, Client | OPEN, chưa merge; feature/client-reliability tại cddaabc | Chưa đủ điều kiện tích hợp cuối/rebase runner |
| PR #6, Runner | DRAFT, head ha-nguyet-s2-concurrent tại 7d4cec4 | Không chứa bản mới trên ha-nguyet; Team Lead cần chốt luồng review |
| ha-nguyet | 15a234f trước cập nhật kế hoạch này; có code, test và mẫu loopback | Giữ làm nhánh duy nhất cho các cập nhật CN21-13 |

Tại thời điểm rà soát, PR #6/#7/#8 chưa có review hoặc bình luận. Nội dung PR #8 báo 35 test reliability PASS; đây là báo cáo của PR, không phải kết quả chạy lại trong lần rà soát này.

## 3. Kiểm tra interface client trước tích hợp

PR #8 đã có SERVER_BUSY fatal, FILE_BUSY recoverable, bảo vệ thao tác FileClient giữa các thread, xử lý file local bị khóa và cleanup download. Không được ghi đè các hành vi này bằng client.py cũ.

Tuy nhiên constructor tại cddaabc chưa nhận các tham số mà WorkerClient hiện truyền:

- num_clients;
- client_id;
- session_id;
- csv_fields;
- socket_timeout.

Measurement trong PR #8 cũng chưa truyền các định danh/số client này và gọi logger schema mặc định Sprint 1. Nếu copy trực tiếp client.py của PR #8 vào runner, có thể lỗi constructor hoặc ghi sai schema/num_clients. Đây là điểm cần ghép sau merge, không phải lý do bỏ tính năng reliability.

Sau PR #8 merge, phần ghép phải giữ:

| Client Reliability | Measurement/runner |
| --- | --- |
| SERVER_BUSY fatal, FILE_BUSY recoverable | num_clients, client_id, session_id đúng từng lượt |
| connect không đợi greeting | socket_timeout cấu hình theo runner |
| exclusive operation guard | Một FileClient riêng mỗi worker, không dùng chung socket |
| Upload chờ READY, file local lỗi không phá phiên | READY gate chỉ cho upload đầu, không thêm wire frame |
| Download cleanup .part, giữ file cũ khi lỗi | download_dir riêng từng instance/worker |
| Error classification, reconnect thủ công | CSV mở rộng riêng Sprint 2 và schema Sprint 1 giữ nguyên |

## 4. Các bước thực hiện và điều kiện mở khóa

| Bước | Điều kiện | Trạng thái |
| --- | --- | --- |
| Rà soát trạng thái PR/ref, lịch và API mới | Có thông báo điều phối và source GitHub | Đã thực hiện |
| Cập nhật kế hoạch, test plan và checklist cho locked(...) | Có quyết định API mới | Đã thực hiện trong nhánh ha-nguyet |
| Giữ runner/test/CSV đã chuẩn bị | Có code tại 15a234f và kết quả 22/11 | Đã có; không ghi lại số đo thành ngày hôm nay |
| Tích hợp cuối client.py | PR #8 thực sự merged, có SHA merge và source trên main | BLOCKED — không thực hiện sớm |
| Đồng bộ/rebase theo yêu cầu Team Lead | PR #8 merged và chốt cách đưa cập nhật ha-nguyet vào luồng PR #6 | BLOCKED — không đổi hoặc force-push nhánh PR #6 |
| Test đầy đủ bản ghép | Backend locked(...) được tích hợp, Client Reliability merge và runner ghép xong | BLOCKED |
| Windows/Python 3.11 và LAN | Có hai máy, metadata/revision thật và bản tích hợp | PENDING |

Không đổi baseline Sprint 1, không sửa source Server/Storage/Protocol, không tự merge main và không cập nhật Jira/comment thay owner trong bước chuẩn bị này.

## 5. Ma trận kiểm thử sau khi đủ đầu vào

1. Chạy toàn bộ test reliability của PR #8, test runner và regression Sprint 1 bằng pytest.
2. Chạy 1/5/10 client, ba file 1/10/50 MB, upload/download; đối chiếu 6/30/60 dòng, UUID, num_clients, checksum và overlap.
3. Xác minh SERVER_BUSY đóng/reset session, FILE_BUSY trước READY/OK, không payload khi bị từ chối; không tự retry giữa payload.
4. Kiểm tra reconnect, download đứt/timeout và file local bị khóa; giữ guard chống dùng cùng FileClient đồng thời.
5. Kiểm tra một worker lỗi không chặn worker khác; schema/context/metric CSV sai phải FAIL, baseline cũ giữ nguyên.
6. Chạy Windows/Python 3.11 và LAN theo test plan, thu metadata/log/CSV và revision của cả hai phía. Không dùng mẫu loopback thay nghiệm thu LAN.
7. Cập nhật kết quả trên nhánh ha-nguyet; Team Lead review và quyết định trạng thái DONE sau khi các gate đạt hoặc chấp nhận ngoại lệ có ghi nhận.

## 6. Kết quả đã có và giới hạn

Kết quả **22/11**: 56 test runner PASS, 60 test server riêng PASS; loopback 1/5/10 client PASS với server a07b950. Xem [sprint2-verification.md](sprint2-verification.md). Những kết quả này không chứng minh PR #8 hoặc Backend locked(...) đã được tích hợp.

Trạng thái hiện tại: **CN21-13 — code chuẩn bị sẵn, chờ dependency/review; chưa DONE.**
