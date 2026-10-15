// Pure presentation adapter: WhatsApp data and Instagram data stay in their
// original tables and APIs. Never pass an Instagram row to a WhatsApp action.
export function buildUnifiedInboxRows({
  whatsapp = [],
  instagram = [],
  channel = 'all',
  conversationView = 'inbox',
  searchQuery = '',
} = {}) {
  const safeWhatsApp = channel === 'instagram' ? [] : whatsapp.map((item) => ({
    ...item,
    channel: 'whatsapp',
    rowKey: `wa:${item.id}`,
  }));

  // Instagram assignment/archive workflow is not implemented. Only show IG
  // in the normal Open inbox; don't misrepresent it in Mine/Follow Up/Archive.
  const showInstagram = channel !== 'whatsapp' && conversationView === 'inbox';
  const query = searchQuery.trim().toLocaleLowerCase();

  const safeInstagram = !showInstagram ? [] : instagram
    .filter((item) => item.status !== 'archived')
    .filter((item) => !query || [
      item.contact_name,
      item.account_name,
      item.external_customer_id,
    ].some((value) => String(value || '').toLocaleLowerCase().includes(query)))
    .map((item) => ({
      ...item,
      channel: 'instagram',
      rowKey: `ig:${item.tenant_id}:${item.channel_account_id}:${item.id}`,
    }));

  // Newest first, with a stable tie order. Do not mutate API state.
  return [...safeWhatsApp, ...safeInstagram].sort((left, right) => {
    const time = (item) => {
      const parsed = Date.parse(item.last_message_at || item.updated_at || '');
      return Number.isFinite(parsed) ? parsed : 0;
    };
    return time(right) - time(left);
  });
}
