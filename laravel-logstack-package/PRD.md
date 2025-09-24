# Laravel LogStack Package - Technical PRD

**Package Name:** `laravel-logstack`  
**Version:** 1.0.0  
**Target:** Laravel 8.x - 11.x  
**PHP:** ^8.1  

## Overview

Composer package providing seamless integration between Laravel applications and LogStack log ingestion service. Enables centralized logging across multiple Laravel deployments with native Laravel logging interface compatibility.

## Core Requirements

### 1. Custom Logging Driver
- **Driver Name:** `logstack`
- **Interface:** Implements `Psr\Log\LoggerInterface` via Laravel's logging system
- **Integration:** Registers via `config/logging.php` channels
- **Async Support:** Queue-based logging with configurable batching

### 2. HTTP Client Integration
- **Protocol:** HTTP/1.1 with keep-alive
- **Authentication:** Bearer token with per-app API keys
- **Format:** JSON payload matching LogStack `/v1/logs:ingest` schema
- **Retry Logic:** Exponential backoff (5s, 10s, 20s) with circuit breaker
- **Timeout:** 10s connection, 30s request timeout

### 3. Log Format Transformation
```php
// Laravel Log Entry → LogStack Format
[
    'timestamp' => '2024-01-15T10:30:00.000Z',  // RFC3339
    'level' => 'ERROR',                         // LogLevel enum
    'message' => 'Payment failed',              // string
    'service' => 'laravel-ecommerce',           // config-defined
    'env' => 'production',                      // config-defined
    'labels' => [                               // optional, max 6 keys
        'region' => 'us-east-1',
        'tenant' => 'customer-123'
    ],
    'trace_id' => $request->header('X-Trace-ID'), // optional
    'metadata' => [                             // Laravel context
        'user_id' => auth()->id(),
        'request_id' => $request->id(),
        'url' => $request->fullUrl()
    ]
]
```

### 4. Configuration Schema
```php
// config/logstack.php
return [
    'url' => env('LOGSTACK_URL'),
    'token' => env('LOGSTACK_TOKEN'),
    'service_name' => env('LOGSTACK_SERVICE', app()->getName()),
    'environment' => env('LOGSTACK_ENV', app()->environment()),
    
    // Performance
    'async' => env('LOGSTACK_ASYNC', true),
    'batch_size' => env('LOGSTACK_BATCH_SIZE', 50),
    'batch_timeout_ms' => env('LOGSTACK_BATCH_TIMEOUT', 5000),
    'queue_connection' => env('LOGSTACK_QUEUE', 'default'),
    
    // Labels
    'default_labels' => [
        'region' => env('AWS_REGION'),
        'version' => env('APP_VERSION'),
    ],
    'label_extractors' => [
        'tenant' => TenantLabelExtractor::class,
        'user_type' => UserTypeLabelExtractor::class,
    ],
    
    // HTTP Client
    'timeout' => 30,
    'retry_attempts' => 3,
    'retry_delay_ms' => [5000, 10000, 20000],
];
```

### 5. Service Provider Architecture
```php
LogStackServiceProvider::class
├── registerLogDriver()      // Custom 'logstack' driver
├── registerHttpClient()     // Guzzle with retry middleware
├── registerLabelExtractors() // Dynamic label population
├── publishConfig()          // Vendor publish assets
└── registerCommands()       // Artisan commands
```

## Technical Specifications

### Core Components

#### LogStackLogger
- **Extends:** `Monolog\Logger`
- **Handler:** `LogStackHandler` (custom Monolog handler)
- **Processor:** `LaravelContextProcessor` (adds request/user context)
- **Formatter:** `LogStackFormatter` (transforms to LogStack schema)

#### LogStackHandler
- **Sync Mode:** Direct HTTP POST to LogStack
- **Async Mode:** Dispatch `ProcessLogBatch` job
- **Batching:** Accumulate entries until batch_size or timeout
- **Error Handling:** Fallback to file/syslog on LogStack failure

#### HTTP Client Stack
```php
$stack = HandlerStack::create();
$stack->push(Middleware::retry(
    decider: $this->retryDecider(),
    delay: $this->exponentialDelay()
));
$stack->push(Middleware::timeout($timeout));

$client = new Client(['handler' => $stack]);
```

#### Queue Integration
```php
// Job: ProcessLogBatch
class ProcessLogBatch implements ShouldQueue
{
    public array $entries;
    public int $tries = 3;
    public int $backoff = 60;
    
    public function handle(LogStackClient $client): void
    {
        $client->ingest($this->entries);
    }
}
```

### Middleware Integration

#### Request Logging Middleware
```php
class LogStackRequestMiddleware
{
    public function handle(Request $request, Closure $next): Response
    {
        $startTime = microtime(true);
        $response = $next($request);
        
        Log::channel('logstack')->info('request_completed', [
            'method' => $request->method(),
            'uri' => $request->getRequestUri(),
            'status' => $response->getStatusCode(),
            'duration_ms' => (microtime(true) - $startTime) * 1000,
            'user_id' => auth()->id(),
            'ip' => $request->ip(),
        ]);
        
        return $response;
    }
}
```

### Performance Requirements

- **Throughput:** Handle 1000+ logs/minute per Laravel instance
- **Latency:** <5ms overhead in async mode, <100ms in sync mode
- **Memory:** <10MB additional memory usage under normal load
- **Reliability:** 99.9% delivery rate with fallback mechanisms

### Error Handling

#### Circuit Breaker Pattern
```php
class LogStackCircuitBreaker
{
    private int $failures = 0;
    private int $threshold = 5;
    private int $timeout = 300; // 5 minutes
    private ?Carbon $lastFailure = null;
    
    public function canAttempt(): bool
    {
        if ($this->failures < $this->threshold) return true;
        
        return $this->lastFailure?->addSeconds($this->timeout)->isPast() ?? true;
    }
}
```

#### Fallback Strategy
1. **Primary:** LogStack HTTP endpoint
2. **Secondary:** Laravel's default log channel
3. **Tertiary:** Syslog for critical errors

### Security Considerations

- **Token Storage:** Environment variables only, never in config files
- **TLS:** HTTPS required for LogStack communication
- **Data Sanitization:** PII masking via configurable field patterns
- **Rate Limiting:** Client-side rate limiting to respect LogStack limits

### Installation & Usage

```bash
# Installation
composer require yourcompany/laravel-logstack

# Publish config
php artisan vendor:publish --provider="LogStackServiceProvider"

# Environment setup
LOGSTACK_URL=https://logstack.yourcompany.com
LOGSTACK_TOKEN=logstack_laravel_app1_abc123
LOGSTACK_SERVICE=ecommerce-api
LOGSTACK_ENV=production
```

```php
// Usage - logging.php channel configuration
'channels' => [
    'logstack' => [
        'driver' => 'logstack',
        'level' => 'debug',
    ],
    
    'stack' => [
        'driver' => 'stack',
        'channels' => ['logstack', 'daily'], // Dual logging
    ],
],

// Application usage
Log::channel('logstack')->error('Payment processing failed', [
    'order_id' => $order->id,
    'payment_method' => $payment->method,
]);
```

## Validation Criteria

### Functional Tests
- [ ] Log entries reach LogStack service correctly
- [ ] Async batching accumulates and flushes properly
- [ ] Fallback mechanisms activate on LogStack failures
- [ ] Label extractors populate dynamic labels
- [ ] Circuit breaker prevents cascade failures

### Performance Tests
- [ ] 1000 logs/minute sustained throughput
- [ ] <100ms P99 latency in sync mode
- [ ] <5ms P99 latency in async mode
- [ ] Memory usage under 10MB additional

### Integration Tests
- [ ] Compatible with Laravel 8.x through 11.x
- [ ] Works with common queue drivers (Redis, Database, SQS)
- [ ] Graceful degradation when LogStack unavailable
- [ ] Proper service provider registration

## Delivery Timeline

- **Week 1:** Core logging driver and HTTP client
- **Week 2:** Async batching and queue integration
- **Week 3:** Middleware, label extractors, error handling
- **Week 4:** Testing, documentation, package publishing

## Dependencies

```json
{
    "require": {
        "php": "^8.1",
        "laravel/framework": "^8.0|^9.0|^10.0|^11.0",
        "guzzlehttp/guzzle": "^7.0",
        "monolog/monolog": "^2.0|^3.0"
    },
    "require-dev": {
        "orchestra/testbench": "^6.0|^7.0|^8.0",
        "phpunit/phpunit": "^9.0|^10.0"
    }
}
```
