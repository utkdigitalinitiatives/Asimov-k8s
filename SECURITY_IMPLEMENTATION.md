# Solr Security Implementation with Azure Key Vault

This guide implements basic authentication for Solr instances using Azure Key Vault for secrets management in a GitOps-friendly way.

## Architecture Overview

- **Azure Key Vault**: Stores Solr admin credentials
- **Azure Key Vault CSI Driver**: Syncs secrets from Key Vault to Kubernetes
- **Workload Identity**: Provides secure authentication between AKS pods and Azure Key Vault
- **Solr Basic Auth**: Implements security.json with admin credentials
- **GitOps**: All configuration in git, no secrets in repository

## Prerequisites

- Azure CLI installed and authenticated
- kubectl configured for asimov cluster
- Appropriate permissions in Azure subscription

## Implementation Steps

### Step 1: Enable Azure Key Vault CSI Driver on AKS

```bash
# Enable the Azure Key Vault provider for Secrets Store CSI driver
az aks enable-addons \
  --addons azure-keyvault-secrets-provider \
  --name asimov \
  --resource-group rg-asimov

# Enable workload identity (if not already enabled)
az aks update \
  --name asimov \
  --resource-group rg-asimov \
  --enable-oidc-issuer \
  --enable-workload-identity

# Get the OIDC issuer URL (save this for later)
export AKS_OIDC_ISSUER=$(az aks show \
  --name asimov \
  --resource-group rg-asimov \
  --query "oidcIssuerProfile.issuerUrl" \
  --output tsv)

echo "OIDC Issuer URL: $AKS_OIDC_ISSUER"
```

### Step 2: Create Azure Key Vault

```bash
# Create Key Vault
az keyvault create \
  --name kv-asimov-shared \
  --resource-group rg-asimov \
  --location eastus2 \
  --enable-rbac-authorization true

# Get Key Vault resource ID
export KEYVAULT_RESOURCE_ID=$(az keyvault show \
  --name kv-asimov-shared \
  --resource-group rg-asimov \
  --query id \
  --output tsv)

echo "Key Vault Resource ID: $KEYVAULT_RESOURCE_ID"
```

### Step 3: Generate and Store Solr Admin Credentials

```bash
# Generate strong random password
export SOLR_ADMIN_PASSWORD=$(openssl rand -base64 32)

# Store credentials in Key Vault
az keyvault secret set \
  --vault-name kv-asimov-shared \
  --name solr-admin-username \
  --value "admin"

az keyvault secret set \
  --vault-name kv-asimov-shared \
  --name solr-admin-password \
  --value "$SOLR_ADMIN_PASSWORD"

echo "Credentials stored in Key Vault"
echo "Admin username: admin"
echo "Admin password: $SOLR_ADMIN_PASSWORD"
echo ""
echo "IMPORTANT: Save the password securely! It will be needed for manual access."
```

### Step 4: Create Managed Identities and Configure Workload Identity

```bash
# Create managed identity for solr-mainsite
az identity create \
  --name solr-mainsite-identity \
  --resource-group rg-asimov \
  --location eastus2

# Get client ID and principal ID for mainsite
export MAINSITE_CLIENT_ID=$(az identity show \
  --name solr-mainsite-identity \
  --resource-group rg-asimov \
  --query clientId \
  --output tsv)

export MAINSITE_PRINCIPAL_ID=$(az identity show \
  --name solr-mainsite-identity \
  --resource-group rg-asimov \
  --query principalId \
  --output tsv)

# Create managed identity for solr-volopedia
az identity create \
  --name solr-volopedia-identity \
  --resource-group rg-asimov \
  --location eastus2

# Get client ID and principal ID for volopedia
export VOLOPEDIA_CLIENT_ID=$(az identity show \
  --name solr-volopedia-identity \
  --resource-group rg-asimov \
  --query clientId \
  --output tsv)

export VOLOPEDIA_PRINCIPAL_ID=$(az identity show \
  --name solr-volopedia-identity \
  --resource-group rg-asimov \
  --query principalId \
  --output tsv)

echo "Mainsite Client ID: $MAINSITE_CLIENT_ID"
echo "Volopedia Client ID: $VOLOPEDIA_CLIENT_ID"
```

### Step 5: Grant Key Vault Access to Managed Identities

```bash
# Grant Key Vault Secrets User role to mainsite identity
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee-object-id "$MAINSITE_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --scope "$KEYVAULT_RESOURCE_ID"

# Grant Key Vault Secrets User role to volopedia identity
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee-object-id "$VOLOPEDIA_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --scope "$KEYVAULT_RESOURCE_ID"

echo "Key Vault access granted to both identities"
```

### Step 6: Create Federated Identity Credentials

```bash
# Create federated credential for solr-mainsite
az identity federated-credential create \
  --name solr-mainsite-federated-credential \
  --identity-name solr-mainsite-identity \
  --resource-group rg-asimov \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject system:serviceaccount:solr-mainsite:solr-mainsite-sa

# Create federated credential for solr-volopedia
az identity federated-credential create \
  --name solr-volopedia-federated-credential \
  --identity-name solr-volopedia-identity \
  --resource-group rg-asimov \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject system:serviceaccount:solr-volopedia:solr-volopedia-sa

echo "Federated credentials created"
```

### Step 7: Update Kubernetes Manifests

The following manifests need to be created/updated in the repository:

1. `apps/base/solr-mainsite/serviceaccount.yaml` - ServiceAccount with workload identity
2. `apps/base/solr-mainsite/secretproviderclass.yaml` - SecretProviderClass for Key Vault
3. `apps/base/solr-mainsite/security-config.yaml` - security.json ConfigMap
4. `apps/base/solr-mainsite/solrcloud.yaml` - Updated with security configuration
5. Similar files for `solr-volopedia`

### Step 8: Apply Configuration Variables

After running the Azure commands above, update the following in the Kubernetes manifests:

**For solr-mainsite:**
- Replace `${MAINSITE_CLIENT_ID}` with the actual client ID
- Replace `${KEYVAULT_NAME}` with `kv-asimov-shared`
- Replace `${TENANT_ID}` with your Azure tenant ID

**For solr-volopedia:**
- Replace `${VOLOPEDIA_CLIENT_ID}` with the actual client ID
- Replace `${KEYVAULT_NAME}` with `kv-asimov-shared`
- Replace `${TENANT_ID}` with your Azure tenant ID

```bash
# Get your tenant ID
export TENANT_ID=$(az account show --query tenantId --output tsv)
echo "Tenant ID: $TENANT_ID"

# Summary of values to use in manifests:
echo ""
echo "=== Configuration Summary ==="
echo "Key Vault Name: kv-asimov-shared"
echo "Tenant ID: $TENANT_ID"
echo "Mainsite Client ID: $MAINSITE_CLIENT_ID"
echo "Volopedia Client ID: $VOLOPEDIA_CLIENT_ID"
echo "============================"
```

### Step 9: Commit and Push Changes

After creating all manifest files and substituting the values:

```bash
git add apps/base/solr-mainsite/
git add apps/base/solr-volopedia/
git commit -m "Add Solr basic authentication with Azure Key Vault integration"
git push origin main
```

### Step 10: Verify Deployment

```bash
# Wait for FluxCD to sync (1-2 minutes)
# Check SecretProviderClass
kubectl get secretproviderclass -n solr-mainsite
kubectl get secretproviderclass -n solr-volopedia

# Check if secrets were created
kubectl get secrets -n solr-mainsite | grep solr-auth
kubectl get secrets -n solr-volopedia | grep solr-auth

# Check Solr pods are running
kubectl get pods -n solr-mainsite
kubectl get pods -n solr-volopedia

# Test authentication
curl -u admin:$SOLR_ADMIN_PASSWORD https://solr-main.libutk.com/solr/admin/info/health
```

## Security Considerations

1. **Password Rotation**: Update Key Vault secret and restart Solr pods
2. **RBAC**: Managed identities have minimal permissions (only read secrets from specific Key Vault)
3. **No Secrets in Git**: All sensitive data stored in Azure Key Vault
4. **Workload Identity**: Modern, secure authentication without service principal credentials
5. **TLS**: All external access via HTTPS with Let's Encrypt certificates

## Troubleshooting

### Secrets not syncing from Key Vault
```bash
# Check CSI driver pods
kubectl get pods -n kube-system | grep secrets-store

# Check SecretProviderClass events
kubectl describe secretproviderclass solr-auth-provider -n solr-mainsite

# Check pod events
kubectl describe pod <solr-pod-name> -n solr-mainsite
```

### Authentication not working
```bash
# Check if security.json exists in ZooKeeper
kubectl exec -it staging-solr-mainsite-solrcloud-0 -n solr-mainsite -- \
  /opt/solr/server/scripts/cloud-scripts/zkcli.sh -zkhost \
  shared-zookeeper-0.shared-zookeeper-headless.solr-system.svc.cluster.local:2181/mainsite \
  -cmd get /security.json

# Check Solr logs
kubectl logs <solr-pod-name> -n solr-mainsite
```

## Additional Resources

- [Solr Basic Authentication Plugin](https://solr.apache.org/guide/solr/latest/deployment-guide/basic-authentication-plugin.html)
- [Azure Key Vault CSI Driver](https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver)
- [Azure Workload Identity](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview)
