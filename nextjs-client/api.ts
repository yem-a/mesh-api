// lib/api.ts
// API client for calling the Python backend

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * Mesh API Client
 * 
 * All business logic lives in the Python backend.
 * This client is a thin wrapper for making API calls.
 */
export const api = {
  // ============================================
  // Authentication / OAuth
  // ============================================
  
  /**
   * Get Stripe OAuth URL - redirects user to Stripe
   */
  getStripeConnectUrl: (userId: string) => 
    `${API_URL}/auth/stripe/connect?user_id=${userId}`,
  
  /**
   * Get QuickBooks OAuth URL - redirects user to QuickBooks
   */
  getQuickBooksConnectUrl: (userId: string) => 
    `${API_URL}/auth/quickbooks/connect?user_id=${userId}`,
  
  /**
   * Check connection status for a user
   */
  getConnectionStatus: async (userId: string) => {
    const res = await fetch(`${API_URL}/auth/status/${userId}`);
    return res.json();
  },

  // ============================================
  // Sync
  // ============================================
  
  /**
   * Sync Stripe transactions
   */
  syncStripe: async (userId: string, days: number = 30) => {
    const res = await fetch(`${API_URL}/sync/stripe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, days }),
    });
    return res.json();
  },

  /**
   * Sync QuickBooks transactions
   */
  syncQuickBooks: async (userId: string, days: number = 30) => {
    const res = await fetch(`${API_URL}/sync/quickbooks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, days }),
    });
    return res.json();
  },

  /**
   * Sync both Stripe and QuickBooks
   */
  syncAll: async (userId: string, days: number = 30) => {
    const res = await fetch(`${API_URL}/sync/all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, days }),
    });
    return res.json();
  },

  // ============================================
  // Reconciliation
  // ============================================
  
  /**
   * Run reconciliation
   */
  reconcile: async (userId: string, options?: { enhanceWithAi?: boolean; persist?: boolean }) => {
    const res = await fetch(`${API_URL}/reconcile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        enhance_with_ai: options?.enhanceWithAi ?? true,
        persist: options?.persist ?? true,
      }),
    });
    return res.json();
  },

  /**
   * Get reconciliation results
   */
  getReconciliationResults: async (userId: string) => {
    const res = await fetch(`${API_URL}/reconcile/${userId}/results`);
    return res.json();
  },

  // ============================================
  // Matches
  // ============================================
  
  /**
   * Get matches with optional filters
   */
  getMatches: async (
    userId: string, 
    filters?: { 
      status?: string; 
      hasDiscrepancy?: boolean; 
      severity?: string;
      limit?: number;
      offset?: number;
    }
  ) => {
    const params = new URLSearchParams({ user_id: userId });
    if (filters?.status) params.append('status', filters.status);
    if (filters?.hasDiscrepancy !== undefined) params.append('has_discrepancy', String(filters.hasDiscrepancy));
    if (filters?.severity) params.append('severity', filters.severity);
    if (filters?.limit) params.append('limit', String(filters.limit));
    if (filters?.offset) params.append('offset', String(filters.offset));
    
    const res = await fetch(`${API_URL}/matches?${params}`);
    return res.json();
  },

  /**
   * Get discrepancies
   */
  getDiscrepancies: async (
    userId: string,
    filters?: { severity?: string; limit?: number; offset?: number }
  ) => {
    const params = new URLSearchParams({ user_id: userId });
    if (filters?.severity) params.append('severity', filters.severity);
    if (filters?.limit) params.append('limit', String(filters.limit));
    if (filters?.offset) params.append('offset', String(filters.offset));
    
    const res = await fetch(`${API_URL}/matches/discrepancies?${params}`);
    return res.json();
  },

  /**
   * Get a single match
   */
  getMatch: async (matchId: string, userId: string) => {
    const res = await fetch(`${API_URL}/matches/${matchId}?user_id=${userId}`);
    return res.json();
  },

  /**
   * Resolve a match
   */
  resolveMatch: async (
    matchId: string, 
    userId: string, 
    action: string, 
    notes?: string,
    adjustmentAmount?: number
  ) => {
    const res = await fetch(`${API_URL}/matches/${matchId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        user_id: userId, 
        action, 
        notes,
        adjustment_amount: adjustmentAmount,
      }),
    });
    return res.json();
  },

  /**
   * Get AI suggestion for a match
   */
  getAiSuggestion: async (matchId: string, userId: string) => {
    const res = await fetch(`${API_URL}/matches/${matchId}/suggestion?user_id=${userId}`);
    return res.json();
  },

  /**
   * Get AI explanation for a match
   */
  getAiExplanation: async (matchId: string, userId: string) => {
    const res = await fetch(`${API_URL}/matches/${matchId}/explain?user_id=${userId}`);
    return res.json();
  },

  // ============================================
  // Health
  // ============================================
  
  /**
   * Check API health
   */
  healthCheck: async () => {
    const res = await fetch(`${API_URL}/health`);
    return res.json();
  },
};

// Export types for convenience
export type Api = typeof api;
