import fs from 'fs';
import yaml from 'js-yaml';
import path from 'path';

/**
 * Build configuration script that reads config.yaml and generates environment variables
 */
function generateProductionConfig() {
  try {
    // Read config.yaml from parent directory
    const configPath = path.resolve('..', 'config.yaml');

    if (!fs.existsSync(configPath)) {
      console.warn(`Config file not found at ${configPath}, using defaults`);
      return {
        host: '0.0.0.0',
        port: 8080
      };
    }

    const configContent = fs.readFileSync(configPath, 'utf8');
    const config = yaml.load(configContent);

    const serverConfig = config.server || {};
    const host = serverConfig.host || '0.0.0.0';
    const port = serverConfig.port || 8080;

    console.log(`Read config from ${configPath}:`);
    console.log(`  Host: ${host}`);
    console.log(`  Port: ${port}`);

    return { host, port };
  } catch (error) {
    console.error('Error reading config.yaml:', error.message);
    console.log('Using default configuration');
    return {
      host: '0.0.0.0',
      port: 8080
    };
  }
}

function writeEnvProduction() {
  const { host, port } = generateProductionConfig();

  // Generate API base URL
  // In production, use the same host and port as the backend server
  const apiBaseUrl = `http://${host === '0.0.0.0' ? 'localhost' : host}:${port}`;

  const envContent = `# Auto-generated production environment variables
# Generated from ../config.yaml at build time
VITE_API_BASE_URL=${apiBaseUrl}
VITE_SERVER_HOST=${host}
VITE_SERVER_PORT=${port}
`;

  fs.writeFileSync('.env.production', envContent);
  console.log('Generated .env.production with API base URL:', apiBaseUrl);
}

// Run the script if called directly
if (import.meta.url === `file:///${process.argv[1].replace(/\\/g, '/')}`) {
  writeEnvProduction();
}

// Also run if this is the main module (fallback)
if (process.argv[1] && process.argv[1].endsWith('build-config.js')) {
  writeEnvProduction();
}

export { generateProductionConfig, writeEnvProduction };

