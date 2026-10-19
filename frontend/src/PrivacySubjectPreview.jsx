import { useState } from 'react';
import { previewPrivacyConversation } from './api';
import './PrivacySubjectPreview.css';

/** Ephemeral, non-identifying staging preview — no case linkage or deletion. */
export default function PrivacySubjectPreview({ tenantId, caseRef, status }) {
  const [relation, setRelation] = useState('unknown');
  const [platform, setPlatform] = useState('instagram');
  const [conversationId, setConversationId] = useState('');
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  function reset() {
    setPreview(null);
    setError('');
  }

  async function checkConversation(event) {
    event.preventDefault();
    const value = Number(conversationId);
    if (!Number.isSafeInteger(value) || value < 1 || busy) {
      setError('Enter a valid positive conversation ID.');
      return;
    }
    reset();
    setBusy(true);
    try {
      const result = await previewPrivacyConversation(tenantId, caseRef, platform, value);
      setPreview(result);
    } catch (cause) {
      if (cause?.status === 403) {
        setError('Recent Authenticator login and company owner/admin permission required.');
      } else if (cause?.status === 404) {
        setError('No Instagram conversation found for this company and ID.');
      } else if (cause?.status === 409) {
        setError('Identity review is required, or this channel is not yet safely supported.');
      } else if (cause?.status === 429) {
        setError('Too many searches. Please wait one minute.');
      } else {
        setError('Could not inspect this conversation. No changes were made.');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="gdpr-subject-inspection" aria-label="Sendro subject data preview">
      <h3>Sendro records — preview only</h3>
      <p>Does this request concern data held in Sendro? This selection is not saved or connected to the case.</p>
      <label htmlFor="gdpr-data-relationship">Related to Sendro?</label>
      <select id="gdpr-data-relationship" value={relation}
        onChange={(event) => { setRelation(event.target.value); reset(); }}>
        <option value="unknown">Not sure</option>
        <option value="no">No</option>
        <option value="yes">Yes — inspect a conversation</option>
      </select>
      {relation === 'yes' && (
        <form onSubmit={checkConversation} className="gdpr-subject-form">
          <label htmlFor="gdpr-subject-platform">Channel</label>
          <select id="gdpr-subject-platform" value={platform}
            onChange={(event) => { setPlatform(event.target.value); reset(); }}>
            <option value="instagram">Instagram</option>
            <option value="whatsapp">WhatsApp (tenant mapping pending)</option>
          </select>
          {platform === 'whatsapp' ? (
            <p role="status">WhatsApp preview is disabled until we can prove the exact company owns the conversation. No phone-based lookup is allowed.</p>
          ) : (
            <>
              <label htmlFor="gdpr-subject-id">Instagram conversation ID (not the customer name)</label>
              <input id="gdpr-subject-id" type="number" min="1" step="1"
                value={conversationId} onChange={(event) => { setConversationId(event.target.value); reset(); }}
                placeholder="Exact conversation ID" autoComplete="off" />
              {status === 'received' && (
                <p role="status">Mark identity independently verified before inspecting records. An ID alone does not verify who the requester is.</p>
              )}
              <button type="submit" disabled={busy || status === 'received' || !conversationId.trim()}>
                {busy ? 'Checking…' : 'Preview matching records'}
              </button>
            </>
          )}
        </form>
      )}
      {error && <p role="alert" className="gdpr-subject-error">{error}</p>}
      {relation === 'yes' && preview && (
        <div className="gdpr-subject-result" role="status">
          <strong>Instagram conversation #{preview.conversation_id}</strong>
          <p>Messages in Sendro: <strong>{preview.messages}</strong></p>
          <p>Messages with media metadata: <strong>{preview.messages_with_media_metadata}</strong></p>
          <p><strong>Partial inventory only.</strong> Template batches, provider copies, media storage, logs, and backups are not assessed. This is not a complete deletion plan.</p>
          <p>No case linkage was saved. No messages were opened, sent or deleted.</p>
          <button type="button" disabled title="Deletion is not implemented or authorized">Delete customer data — disabled</button>
        </div>
      )}
    </section>
  );
}
