// Pure, defensive presentation adapter for the future Instagram Incident Center.
// NOT wired to Sendro production. Never echo raw API fields, DM data, user IDs,
// guest identifiers, tokens, URLs, or ciphertext in the browser.
const INCIDENT_LABELS = Object.freeze({
  failed_deliveries: 'Instagram deliveries exhausted retries',
  quarantined_deliveries: 'Instagram deliveries need review',
  unresolved_processing_delivery: 'Instagram delivery stuck in processing',
  pending_backlog: 'Instagram inbox processing backlog',
  stale_pending_delivery: 'Instagram delivery waiting too long',
});
const KNOWN_STATES = new Set([
  'pending', 'leased', 'accepted', 'acknowledged', 'failed',
]);

export function buildIncidentCenterRows(incidents) {
  if (!Array.isArray(incidents)) return [];
  return incidents.slice(0, 20)
    .filter((item) => item && typeof item === 'object' && !Array.isArray(item))
    .filter((item) => Object.prototype.hasOwnProperty.call(
      INCIDENT_LABELS, item.code,
    ))
    .filter((item) => (
      Number.isSafeInteger(item.episode) && item.episode > 0
      && Number.isSafeInteger(item.observations) && item.observations > 0
      && typeof item.is_active === 'boolean'
      && KNOWN_STATES.has(item.dispatch_status)
    ))
    .map((item) => ({
      // Deliberately NO object spread: only whitelisted presentational data.
      code: item.code,
      label: INCIDENT_LABELS[item.code],
      episode: item.episode,
      observations: item.observations,
      active: item.is_active,
      status: item.dispatch_status,
      canReview: item.dispatch_status === 'accepted',
    }));
}
