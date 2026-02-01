# Mock API Endpoints

Run the API:

```
uvicorn server:app --reload --port 8000
```

Health check:

```
GET /health
```

## Bureau

```
POST /bureau
```

Body:

```
{
  "name": "Jane Doe",
  "pan": "ABCDE1234F"
}
```

## Bank Statement

```
POST /bank-statement
```

Body:

```
{
  "account_number": "1234567890"
}
```

## Lead Sourcing

```
POST /lead-sourcing
```

Body:

```
{
  "lead_id": "L-1001"
}
```

## Static Files

```
GET /images/<path>
```

Examples:

```
/images/adhaar/1234-5678-9012.png
/images/selfie/L-1001_selfie.png
/images/payslip/L-1001_payslip.pdf
```
