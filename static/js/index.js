const locationPath = [
  window.location.protocol,
  '//',
  window.location.host,
  window.location.pathname
].join('')

const mapWithdrawLink = function (obj) {
  obj._data = _.clone(obj)
  obj.min_fsat = new Intl.NumberFormat(LOCALE).format(obj.min_withdrawable)
  obj.max_fsat = new Intl.NumberFormat(LOCALE).format(obj.max_withdrawable)
  obj.uses_left = obj.uses - obj.used
  obj.print_url = [locationPath, 'print/', obj.id].join('')
  obj.withdraw_url = [locationPath, obj.id].join('')
  obj._data.use_custom = Boolean(obj.custom_url)
  return obj
}

const CUSTOM_URL = '/static/images/default_voucher.png'

window.app = Vue.createApp({
  el: '#vue',
  mixins: [window.windowMixin],
  data() {
    return {
      checker: null,
      withdrawLinks: [],
      withdrawLinksTable: {
        columns: [
          {name: 'title', align: 'left', label: 'Title', field: 'title'},
          {
            name: 'created_at',
            align: 'left',
            label: 'Created At',
            field: 'created_at',
            sortable: true,
            format: function (val, row) {
              return new Date(val).toLocaleString()
            }
          },
          {
            name: 'wait_time',
            align: 'right',
            label: 'Wait',
            field: 'wait_time'
          },
          {
            name: 'uses',
            align: 'right',
            label: 'Created',
            field: 'uses'
          },
          {
            name: 'uses_left',
            align: 'right',
            label: 'Uses left',
            field: 'uses_left'
          },
          {name: 'min', align: 'right', label: 'Min (sat)', field: 'min_fsat'},
          {name: 'max', align: 'right', label: 'Max (sat)', field: 'max_fsat'}
        ],
        pagination: {
          page: 1,
          rowsPerPage: 10,
          rowsNumber: 0
        }
      },
      nfcTagWriting: false,
      formDialog: {
        show: false,
        secondMultiplier: 'seconds',
        secondMultiplierOptions: ['seconds', 'minutes', 'hours'],
        data: {
          is_unique: false,
          use_custom: false,
          has_webhook: false
        }
      },
      simpleformDialog: {
        show: false,
        data: {
          is_unique: true,
          use_custom: false,
          title: 'Vouchers',
          min_withdrawable: 0,
          wait_time: 1
        }
      },
      qrCodeDialog: {
        show: false,
        data: null
      }
    }
  },
  computed: {
    sortedWithdrawLinks() {
      return this.withdrawLinks.sort(function (a, b) {
        return b.uses_left - a.uses_left
      })
    }
  },
  methods: {
    getWithdrawLinks(props) {
      if (props) {
        this.withdrawLinksTable.pagination = props.pagination
      }

      let pagination = this.withdrawLinksTable.pagination
      const query = {
        limit: pagination.rowsPerPage,
        offset: (pagination.page - 1) * pagination.rowsPerPage
      }

      LNbits.api
        .request(
          'GET',
          `/withdraw/api/v1/links?all_wallets=true&limit=${query.limit}&offset=${query.offset}`,
          this.g.user.wallets[0].inkey
        )
        .then(response => {
          this.withdrawLinks = response.data.data.map(mapWithdrawLink)
          this.withdrawLinksTable.pagination.rowsNumber = response.data.total
        })
        .catch(error => {
          clearInterval(this.checker)
          LNbits.utils.notifyApiError(error)
        })
    },
    closeFormDialog() {
      this.formDialog.data = {
        is_unique: false,
        use_custom: false,
        has_webhook: false
      }
    },
    simplecloseFormDialog() {
      this.simpleformDialog.data = {
        is_unique: false,
        use_custom: false
      }
    },
    openQrCodeDialog(linkId) {
      const link = _.findWhere(this.withdrawLinks, {id: linkId})

      this.qrCodeDialog.data = _.clone(link)
      this.qrCodeDialog.data.url =
        window.location.protocol + '//' + window.location.host
      this.qrCodeDialog.show = true
    },
    openUpdateDialog(linkId) {
      let link = _.findWhere(this.withdrawLinks, {id: linkId})
      link._data.has_webhook = link._data.webhook_url ? true : false
      this.formDialog.data = _.clone(link._data)
      this.formDialog.show = true
    },
    sendFormData() {
      const wallet = _.findWhere(this.g.user.wallets, {
        id: this.formDialog.data.wallet
      })
      const data = _.omit(this.formDialog.data, 'wallet')

      if (!data.use_custom) {
        data.custom_url = null
      }

      if (data.use_custom && !data?.custom_url) {
        data.custom_url = CUSTOM_URL
      }

      data.wait_time =
        data.wait_time *
        {
          seconds: 1,
          minutes: 60,
          hours: 3600
        }[this.formDialog.secondMultiplier]

      if (data.id) {
        this.updateWithdrawLink(wallet, data)
      } else {
        this.createWithdrawLink(wallet, data)
      }
    },
    simplesendFormData() {
      const wallet = _.findWhere(this.g.user.wallets, {
        id: this.simpleformDialog.data.wallet
      })
      const data = _.omit(this.simpleformDialog.data, 'wallet')

      data.wait_time = 1
      data.min_withdrawable = data.max_withdrawable
      data.title = 'vouchers'
      data.is_unique = true

      if (!data.use_custom) {
        data.custom_url = null
      }

      if (data.use_custom && !data?.custom_url) {
        data.custom_url = '/static/images/default_voucher.png'
      }

      if (data.id) {
        this.updateWithdrawLink(wallet, data)
      } else {
        this.createWithdrawLink(wallet, data)
      }
    },
    updateWithdrawLink(wallet, data) {
      // Remove webhook info if toggle is set to false
      if (!data.has_webhook) {
        data.webhook_url = null
        data.webhook_headers = null
        data.webhook_body = null
      }

      LNbits.api
        .request(
          'PUT',
          '/withdraw/api/v1/links/' + data.id,
          wallet.adminkey,
          data
        )
        .then(response => {
          this.withdrawLinks = _.reject(this.withdrawLinks, function (obj) {
            return obj.id === data.id
          })
          this.withdrawLinks.push(mapWithdrawLink(response.data))
          this.formDialog.show = false
          this.closeFormDialog()
        })
        .catch(error => {
          LNbits.utils.notifyApiError(error)
        })
    },
    createWithdrawLink(wallet, data) {
      LNbits.api
        .request('POST', '/withdraw/api/v1/links', wallet.adminkey, data)
        .then(response => {
          this.withdrawLinks.push(mapWithdrawLink(response.data))
          this.formDialog.show = false
          this.simpleformDialog.show = false
          this.closeFormDialog()
        })
        .catch(function (error) {
          LNbits.utils.notifyApiError(error)
        })
    },
    deleteWithdrawLink(linkId) {
      const link = _.findWhere(this.withdrawLinks, {id: linkId})

      LNbits.utils
        .confirmDialog('Are you sure you want to delete this withdraw link?')
        .onOk(() => {
          LNbits.api
            .request(
              'DELETE',
              '/withdraw/api/v1/links/' + linkId,
              _.findWhere(this.g.user.wallets, {id: link.wallet}).adminkey
            )
            .then(response => {
              this.withdrawLinks = _.reject(this.withdrawLinks, function (obj) {
                return obj.id === linkId
              })
            })
            .catch(function (error) {
              LNbits.utils.notifyApiError(error)
            })
        })
    },
    async writeNfcTag(lnurl) {
      try {
        if (typeof NDEFReader == 'undefined') {
          throw {
            toString: function () {
              return 'NFC not supported on this device or browser.'
            }
          }
        }

        const ndef = new NDEFReader()

        this.nfcTagWriting = true
        this.$q.notify({
          message: 'Tap your NFC tag to write the LNURL-withdraw link to it.'
        })

        await ndef.write({
          records: [{recordType: 'url', data: 'lightning:' + lnurl, lang: 'en'}]
        })

        this.nfcTagWriting = false
        this.$q.notify({
          type: 'positive',
          message: 'NFC tag written successfully.'
        })
      } catch (error) {
        this.nfcTagWriting = false
        this.$q.notify({
          type: 'negative',
          message: error
            ? error.toString()
            : 'An unexpected error has occurred.'
        })
      }
    },
    exportCSV() {
      LNbits.utils.exportCSV(
        this.withdrawLinksTable.columns,
        this.withdrawLinks,
        'withdraw-links'
      )
    }
  },
  created() {
    if (this.g.user.wallets.length) {
      this.getWithdrawLinks()
      this.checker = setInterval(this.getWithdrawLinks, 300000)
    }
  }
})
