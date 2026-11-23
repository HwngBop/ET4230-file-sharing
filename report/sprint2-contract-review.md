# CN21-13 — Review S2-01 v1.0

Ngày rà soát: 23/11/2026. Nguồn yêu cầu: **ET4230-S2-01 — Multi-client Architecture & Protocol Contract v1.0**, Hưng ban hành ngày 20/11/2026, attachment CN21-9. Tài liệu này đối chiếu phần Concurrent Testing/CSV; không thay thế hoặc sửa frozen contract. Thông báo điều phối mới chốt `locked(filename, owner=connection_id)` và chỉ tích hợp runner sau PR #8 merge; xem [kế hoạch hiện tại](sprint2-execution-plan.md).

## 1. Trạng thái

**Code runner: READY FOR REVIEW. Nghiệm thu tổng thể: PENDING. Chưa đủ căn cứ chuyển DONE.**

Review target là nhánh `ha-nguyet`. PR #6 vẫn trỏ `ha-nguyet-s2-concurrent` ở bản cũ; cần Team Lead thống nhất luồng review/tích hợp để không bỏ sót cập nhật. Chưa có xác nhận Jira/review/merge được thực hiện thay thành viên.

## 2. Phần CN21-13 đã triển khai

| Contract | Kiểm chứng |
| --- | --- |
| Mục 5/6, D08: mỗi worker một FileClient/socket | Instance, connection, buffer và địa chỉ socket độc lập |
| Mục 6: filename/download riêng | UUID phiên đầy đủ và client_id trong tên file, thư mục riêng |
| D09, AC02: 5 READY trước payload | Gate có timeout hữu hạn, test server tuần tự không PASS nhầm |
| D08: CSV riêng rồi một writer merge | Worker chỉ ghi CSV riêng; thread chính tổng hợp sau khi tất cả kết thúc |
| Mục 6, AC11: num_clients/session/client IDs | Lưu đúng cấu hình và từ chối CSV sai định danh/cấu hình sau tích hợp |
| D06/D07: SUCCESS chỉ sau checksum | Giữ logic checksum; kiểm tra cả metric của dòng SUCCESS và throughput trống cho FAILED |
| Mục 6: baseline Sprint 1 giữ nguyên | Schema mặc định và dữ liệu đã commit không thay đổi; test sentinel |
| AC11: lỗi trả nonzero, worker khác tiếp tục | Test lỗi một worker, refused connection, CSV sai cấu hình/metric |
| Mục 5 conflict note | Optional constructor fields và default Sprint 1 được giữ; không sửa wire format |

Kiểm tra CSV bổ sung phát hiện: thiếu/lặp thao tác dự kiến, sai client_id/session_id/environment_id/num_clients/chunk, SUCCESS thiếu checksum hoặc metric không hữu hạn/sai công thức, FAILED có throughput. Không sửa số liệu để làm PASS; giữ dòng lỗi và báo FAIL.

Upload đầu tính cả thời gian chờ READY gate. Kết quả chứng minh application dispatch/I/O chồng lấn, không chứng minh CPU song song hay throughput vật lý. Không yêu cầu viết lại cơ chế gate đã có.

## 3. Những phần không tự sửa thay owner

| Dependency | Tình trạng cần review |
| --- | --- |
| S2-02 / CN21-10 — Server | Server concurrent được kiểm tra tại a07b950; cần ghép đúng storage API |
| S2-03 / CN21-11 — Client | PR #8 đã có SERVER_BUSY fatal nhưng còn OPEN; sau merge phải ghép với optional fields của runner, không overwrite |
| S2-04 / CN21-12 — Storage | Theo điều phối mới, locked(filename, owner=connection_id) là API đích; Storage PR #7 có locked, Server a07b950 còn gọi try_lock_file nên Backend chưa tích hợp |
| S2-01 / CN21-9 — Team Lead | Chốt interface/review và xác nhận branch dùng tích hợp; contract cần đổi phải có version mới |
| S2-06 — Integration | Merge theo dependency, full regression tích hợp và LAN E2E do Team Lead điều phối |

Client không chờ greeting ở connect, không gửi payload trước READY. FILE_BUSY được kiểm tra bằng test response recoverable và retry cùng socket. Test này không chứng minh storage production đã có lock. Không thay SERVER_BUSY sang recoverable hoặc đổi tên API để né lỗi tích hợp.

Không chỉnh source Server/Storage/Protocol hoặc tự merge vào main trong phần CN21-13. Các sửa đổi reliability của Member Client cần được giữ khi rebase/merge có thứ tự và chạy lại regression. Không tự động retry payload hoặc phát sinh greeting/frame mới.

## 4. Review gate trước DONE

- [x] Runner 1/5/10 có gate, per-worker CSV, identifiers, metadata và test plan.
- [x] Kiểm chứng loopback AC02/AC11 với server a07b950; kết quả/test log nằm trong sprint2-verification và samples.
- [x] Regression nhánh runner và suite server riêng được thực thi; đây không phải full regression của bản đã tích hợp Storage/Client mới.
- [ ] Team Lead nhận xác nhận S2-01 v1.0 tại CN21-9.
- [ ] Team Lead thống nhất PR/branch review cho bản mới trên ha-nguyet.
- [ ] Backend dùng locked(filename, owner=connection_id), không bỏ qua khóa và đã được tích hợp/review.
- [ ] PR #8 đã merge; runner ghép client.py sau đó, giữ đủ reliability và optional fields.
- [ ] Full regression bản tích hợp PASS theo AC01.
- [ ] Chạy Windows/Python 3.11 sau tích hợp, lưu kết quả thực tế.
- [ ] LAN PC Server Ethernet → laptop Wi-Fi, ít nhất 5 client E2E theo AC12 do Hưng điều phối; lưu CSV/log/metadata và ảnh/capture nếu thu được.
- [ ] Team Lead chấp nhận phạm vi còn loại trừ (nếu có) và duyệt trạng thái cuối.

ACK contract là xác nhận đã thống nhất thiết kế, không thay nghiệm thu hoặc code review. Gate còn mở thì giữ trạng thái REVIEW/IN PROGRESS, không chuyển DONE và không sửa CSV để hợp thức hóa.

## 5. Lịch điều phối hiện tại

Backend hoàn thiện trước 25/11, dự kiến Team Lead review 26/11; Client trước 28/11; runner trước 29/11, tích hợp cuối chỉ sau PR #8 merge. Trạng thái và kế hoạch từng gate được ghi tại [sprint2-execution-plan.md](sprint2-execution-plan.md). Không coi ngày dự kiến là bằng chứng dependency đã hoàn tất.
