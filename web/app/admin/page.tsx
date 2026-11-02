import AdminNoticeEditor from "@/components/AdminNoticeEditor";
import { readNotice } from "@/lib/notice";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const { notice } = await readNotice();
  return <AdminNoticeEditor initialContent={notice.content} />;
}
