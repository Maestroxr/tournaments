export const catalogMessages = {
  he: {
    coinUnit: 'קויינס',
    title: 'מנויים וחבילות קויינס', subtitle: 'ניהול מחירים בכסף אמיתי, כמויות קויינס והרשאות למסלולי המנוי.',
    subscriptions: 'מסלולי מנוי', coins: 'חבילות קויינס', create: 'הוספת חבילת קויינס', edit: 'עריכה',
    name: 'שם המוצר', price: 'מחיר בכסף אמיתי', currency: 'מטבע לתשלום', quantity: 'כמות קויינס בחבילה',
    period: 'תקופת המנוי', months: 'חודשים', month: 'חודש', active: 'פעיל', inactive: 'לא פעיל',
    available: 'פעיל לרכישה בקטלוג', save: 'שמירת שינויים', cancel: 'ביטול', refresh: 'רענון',
    saved: 'המוצר נשמר בהצלחה.', permissions: 'הרשאות המנוי', tier: 'רמת מנוי',
    preparation: 'מחירי הקטלוג משמשים לרכישות Tranzila חדשות. הזמנות קיימות שומרות את המחיר שנקבע בעת יצירתן.',
    impact: 'שינוי הרשאות במסלול חל גם על המנויים הקיימים באותו מסלול. חלק מההרשאות מגדירות זכאות בלבד, ותלויות בזמינות הפיצ׳ר במערכת.',
    empty: 'עדיין אין חבילות קויינס. ניתן להוסיף חבילה ולהגדיר מחיר וכמות.', loading: 'טוען קטלוג…',
    conflict: 'המוצר השתנה מאז שנפתח. רענן את המוצר ובצע את השינויים מחדש כדי לא לדרוס עדכון אחר.',
    reload: 'טעינת הגרסה העדכנית', enabled: 'מותר', disabled: 'ללא הרשאה',
    free: 'ללא תשלום', editing: 'עריכת מוצר', fixedTier: 'רמת המנוי קבועה; ניתן לערוך את השם, המחיר וההרשאות.',
    validation: 'יש למלא שם, מחיר תקין וכמות קויינס שלמה וחיובית. מוצר פעיל בתשלום חייב לעלות יותר מאפס.',
    unavailable: 'לא הוגדרו הרשאות למוצר זה.', perPackage: 'לחבילה', unsaved: 'שינויים שלא נשמרו',
  },
  en: {
    coinUnit: 'coins',
    title: 'Subscriptions & coin packages', subtitle: 'Manage real-money prices, coin quantities and subscription permissions.',
    subscriptions: 'Subscription plans', coins: 'Coin packages', create: 'Add coin package', edit: 'Edit',
    name: 'Product name', price: 'Real-money price', currency: 'Payment currency', quantity: 'Coins per package',
    period: 'Subscription period', months: 'months', month: 'month', active: 'Active', inactive: 'Inactive',
    available: 'Available for purchase in the catalog', save: 'Save changes', cancel: 'Cancel', refresh: 'Refresh',
    saved: 'Product saved successfully.', permissions: 'Subscription permissions', tier: 'Subscription tier',
    preparation: 'Catalog prices apply to new Tranzila purchases. Existing orders retain the price saved when they were created.',
    impact: 'Changing plan permissions also affects existing members on that plan. Some permissions define eligibility only and depend on feature availability in the system.',
    empty: 'No coin packages yet. Add a package and set its price and quantity.', loading: 'Loading catalog…',
    conflict: 'This product has changed since you opened it. Reload it and apply your changes again to avoid overwriting another update.',
    reload: 'Load latest version', enabled: 'Allowed', disabled: 'Not allowed',
    free: 'Free', editing: 'Edit product', fixedTier: 'The subscription tier is fixed; its name, price and permissions can be edited.',
    validation: 'Enter a name, a valid price and a positive whole coin quantity. Active paid products must have a price above zero.',
    unavailable: 'No permissions are configured for this product.', perPackage: 'per package', unsaved: 'Unsaved changes',
  },
}

export const capabilityNames: Record<string, { he: string; en: string }> = {
  online_play: { he: 'משחק אונליין', en: 'Online play' }, tournaments: { he: 'טורנירים', en: 'Tournaments' },
  weekly_cup: { he: 'גביע שבועי', en: 'Weekly cup' }, monthly_cup: { he: 'גביע חודשי', en: 'Monthly cup' },
  grand_championship: { he: 'אליפות ראשית', en: 'Grand championship' }, rating: { he: 'דירוג', en: 'Rating' },
  pr: { he: 'דירוג ביצועים (PR)', en: 'Performance rating (PR)' }, analysis: { he: 'ניתוח משחקים', en: 'Game analysis' },
  courses: { he: 'קורסים', en: 'Courses' }, live_lessons: { he: 'שיעורים חיים', en: 'Live lessons' },
  ai: { he: 'בינה מלאכותית', en: 'AI' }, vip_benefits: { he: 'הטבות VIP', en: 'VIP benefits' },
}

export const capabilityValues: Record<string, { he: string; en: string }> = {
  more: { he: 'מורחב', en: 'Extended' },
  none: { he: 'ללא', en: 'None' }, basic: { he: 'בסיסי', en: 'Basic' }, limited: { he: 'מוגבל', en: 'Limited' },
  full: { he: 'מלא', en: 'Full' }, unlimited: { he: 'ללא הגבלה', en: 'Unlimited' }, advanced: { he: 'מתקדם', en: 'Advanced' },
  partial: { he: 'חלקי', en: 'Partial' }, premium: { he: 'פרימיום', en: 'Premium' },
}
