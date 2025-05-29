import { onMounted, onUnmounted, ref } from 'vue';

/**
 * Device detection composable
 * Provides comprehensive mobile device detection including user agent and responsive breakpoints
 */
export function useDevice() {
  // Reactive states
  const isMobile = ref(false);
  const isTablet = ref(false);
  const screenWidth = ref(0);
  const screenHeight = ref(0);

  // Breakpoints configuration
  const breakpoints = {
    mobile: 768,
    tablet: 1024,
    desktop: 1200
  };

  // User agent based device detection
  const detectUserAgent = (): { mobile: boolean; tablet: boolean; ios: boolean; android: boolean } => {
    if (typeof window === 'undefined') {
      return { mobile: false, tablet: false, ios: false, android: false };
    }

    const userAgent = navigator.userAgent.toLowerCase();

    // Mobile device patterns
    const mobilePatterns = [
      /android.*mobile/,
      /iphone/,
      /ipod/,
      /blackberry/,
      /windows phone/,
      /mobile/
    ];

    // Tablet device patterns
    const tabletPatterns = [
      /ipad/,
      /android(?!.*mobile)/,
      /tablet/,
      /kindle/,
      /playbook/,
      /silk/
    ];

    const isMobileUA = mobilePatterns.some(pattern => pattern.test(userAgent));
    const isTabletUA = tabletPatterns.some(pattern => pattern.test(userAgent));
    const isIOS = /iphone|ipad|ipod/.test(userAgent);
    const isAndroid = /android/.test(userAgent);

    return {
      mobile: isMobileUA,
      tablet: isTabletUA,
      ios: isIOS,
      android: isAndroid
    };
  };

  // Screen size based detection
  const updateScreenSize = () => {
    if (typeof window === 'undefined') return;

    screenWidth.value = window.innerWidth;
    screenHeight.value = window.innerHeight;

    const userAgentInfo = detectUserAgent();

    // Combine user agent and screen size detection
    // Mobile: UA detection OR screen width < mobile breakpoint
    isMobile.value = userAgentInfo.mobile || screenWidth.value < breakpoints.mobile;

    // Tablet: UA detection OR screen width between mobile and desktop (but not mobile UA)
    isTablet.value = userAgentInfo.tablet ||
      (!userAgentInfo.mobile && screenWidth.value >= breakpoints.mobile && screenWidth.value < breakpoints.desktop);
  };

  // Touch capability detection
  const isTouchDevice = ref(false);
  const detectTouchCapability = () => {
    if (typeof window === 'undefined') return false;

    return 'ontouchstart' in window ||
           navigator.maxTouchPoints > 0 ||
           (navigator as any).msMaxTouchPoints > 0;
  };

  // Device orientation
  const orientation = ref<'portrait' | 'landscape'>('portrait');
  const updateOrientation = () => {
    if (typeof window === 'undefined') return;

    orientation.value = window.innerHeight > window.innerWidth ? 'portrait' : 'landscape';
  };

  // Initialize and setup event listeners
  const initialize = () => {
    updateScreenSize();
    updateOrientation();
    isTouchDevice.value = detectTouchCapability();
  };

  const handleResize = () => {
    updateScreenSize();
    updateOrientation();
  };

  // Lifecycle hooks
  onMounted(() => {
    initialize();
    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);
  });

  onUnmounted(() => {
    window.removeEventListener('resize', handleResize);
    window.removeEventListener('orientationchange', handleResize);
  });

  // Computed device type
  const deviceType = ref<'mobile' | 'tablet' | 'desktop'>('desktop');
  const updateDeviceType = () => {
    if (isMobile.value) {
      deviceType.value = 'mobile';
    } else if (isTablet.value) {
      deviceType.value = 'tablet';
    } else {
      deviceType.value = 'desktop';
    }
  };

  // Watch for changes and update device type
  const unwatchMobile = ref(() => {});
  const unwatchTablet = ref(() => {});

  onMounted(() => {
    // Manual watchers to avoid circular dependencies
    const checkDeviceType = () => {
      updateDeviceType();
    };

    // Initial check
    checkDeviceType();

    // Set up manual watchers
    const mobileWatcher = () => checkDeviceType();
    const tabletWatcher = () => checkDeviceType();

    unwatchMobile.value = mobileWatcher;
    unwatchTablet.value = tabletWatcher;
  });

  // Utility functions
  const isScreenSize = (size: keyof typeof breakpoints): boolean => {
    const width = screenWidth.value;
    switch (size) {
      case 'mobile':
        return width < breakpoints.mobile;
      case 'tablet':
        return width >= breakpoints.mobile && width < breakpoints.desktop;
      case 'desktop':
        return width >= breakpoints.desktop;
      default:
        return false;
    }
  };

  const isAtLeast = (size: keyof typeof breakpoints): boolean => {
    return screenWidth.value >= breakpoints[size];
  };

  const isAtMost = (size: keyof typeof breakpoints): boolean => {
    return screenWidth.value <= breakpoints[size];
  };

  // Get user agent info
  const userAgentInfo = detectUserAgent();

  return {
    // Reactive states
    isMobile,
    isTablet,
    isTouchDevice,
    screenWidth,
    screenHeight,
    orientation,
    deviceType,

    // User agent detection results
    isIOS: userAgentInfo.ios,
    isAndroid: userAgentInfo.android,

    // Utility functions
    isScreenSize,
    isAtLeast,
    isAtMost,

    // Breakpoints for external use
    breakpoints,

    // Manual refresh function
    refresh: initialize
  };
}

export default useDevice;
