# Evaluation Criteria: Frontend / UI

## Scoring Rubric

### Correctness (30%)
- Does the UI change match what was requested?
- Interactive elements work (buttons click, forms submit, toggles toggle)
- State updates correctly on user actions
- No broken navigation or dead links

### Visual Quality (25%)
- Matches existing design system (colors, spacing, typography, border radius)
- Layout is consistent with surrounding components
- No overlapping elements, text clipping, or overflow issues
- Icons and images render correctly

### Responsiveness & Accessibility (20%)
- Works at desktop width (1280px+)
- Works at tablet width (768px)
- No horizontal scroll on mobile (375px)
- Tab order is logical
- Color contrast meets WCAG AA (4.5:1 for text)
- Interactive elements have visible focus states

### Browser Compatibility (10%)
- No console errors or warnings
- No unhandled promise rejections
- CSS renders correctly (no broken flexbox/grid)

### Completeness (15%)
- All parts of the UI task are addressed
- Loading states handled (skeleton or spinner)
- Error states handled (network failure, empty data)
- Commits are clean with descriptive messages

## Automatic FAIL Conditions

- Page does not render (white screen, crash)
- Console shows uncaught exceptions
- Build does not compile
- Existing tests fail
- Security vulnerability (XSS, exposed tokens in client code)
- Pushed to main instead of worker/ branch

## Evaluation Method

For UI tasks, you MUST verify visually:
1. Run `/qa` or use `/browse` to open the page in headless browser
2. Navigate to the affected page/component
3. Take a screenshot to verify rendering
4. Click interactive elements to verify they work
5. Check the browser console for errors

Do NOT pass a UI task based solely on reading the code diff.
