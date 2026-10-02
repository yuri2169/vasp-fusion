import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useSignIn } from '../api/queries'
import { Button } from '../components/Button'

const field =
  'h-10 w-full rounded border border-rule-strong bg-surface px-3 text-sm text-fg placeholder:text-muted'

/** Shown when the server requires a login and nobody is signed in (GET /api/auth/me).
 *  The session is a cookie the server sets; nothing is kept in the page. */
export function SignInPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const signIn = useSignIn()
  const userId = useId()
  const passId = useId()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    signIn.mutate({ username: username.trim(), password })
  }

  const refused = signIn.isError
    ? signIn.error instanceof ApiError
      ? signIn.error.detail
      : 'The sign-in could not be completed. Try again.'
    : null

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-5 text-fg">
      <form onSubmit={submit} className="flex w-full max-w-[360px] flex-col gap-4">
        <div>
          <h1 className="display text-xl">Sign in to VASP-FUSION</h1>
          <p className="mt-1.5 text-sm text-muted">Every case opened and every request sent is logged under your name.</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={userId} className="text-sm font-medium">
            User name
          </label>
          <input
            id={userId}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="off"
            spellCheck={false}
            required
            className={field}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={passId} className="text-sm font-medium">
            Password
          </label>
          <input
            id={passId}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className={field}
          />
        </div>
        {refused && (
          <p role="alert" className="rounded border border-seal-text bg-seal-wash px-3 py-2 text-sm text-fg">
            {refused}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={signIn.isPending}>
          {signIn.isPending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </div>
  )
}
